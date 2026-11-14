"""Job Radar API: the Today list, description search and the assistant over HTTP.

    GET  /health          is the service up (no key, no database call; used by deploy checks)
    GET  /jobs/today      the Today list, best fit first, with optional filters
    GET  /jobs/search     search job descriptions by meaning
    POST /ask             ask the assistant a question (costs API money)

Everything except /health needs the header X-API-Key matching JOBRADAR_API_KEY. If that
variable is not set, those endpoints answer 503 rather than run open to the internet.
On Lambda the secrets come from SSM Parameter Store (see load_secrets_from_ssm).

The server never sees the resume: resume_fit is a laptop-only tool, so /ask offers the
assistant run_sql, salary_check and (when an index is present) search_job_text.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from jobradar.agent.sql_guard import check

ROLE_FAMILIES = (
    "Data / BI / AI", "Software", "Integration / solutions", "Business systems / ERP",
    "Technical program / product", "Other",
)  # fmt: skip
TODAY_COLUMNS = (
    "posting_key, company_name, title, location, url, role_family, seniority, "
    "years_required, reach, salary_min_yearly_usd, salary_max_yearly_usd, first_seen, "
    "company_lca_filings, company_median_filed_wage, fit_score"
)


def load_secrets_from_ssm(prefix: str | None = None) -> list[str]:
    """On Lambda, read secrets from SSM Parameter Store into the environment.

    JOBRADAR_SSM_PREFIX (e.g. /job-radar/prod/) is set on the function; each parameter's last
    path part becomes an environment variable (…/DATABRICKS_TOKEN -> DATABRICKS_TOKEN).
    Values already in the environment win. Returns the names loaded, never the values.
    """
    prefix = prefix or os.environ.get("JOBRADAR_SSM_PREFIX")
    if not prefix:
        return []
    import boto3

    ssm = boto3.client("ssm")
    loaded = []
    for page in ssm.get_paginator("get_parameters_by_path").paginate(
        Path=prefix, WithDecryption=True, Recursive=False
    ):
        for param in page["Parameters"]:
            name = param["Name"].rsplit("/", 1)[-1]
            if name not in os.environ:
                os.environ[name] = param["Value"]
                loaded.append(name)
    return loaded


load_secrets_from_ssm()


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("job-radar")
    except Exception:
        return "dev"


@dataclass
class Services:
    """What the endpoints need. Built lazily from .env; tests pass fakes instead."""

    env: str = field(default_factory=lambda: os.environ.get("JOBRADAR_API_ENV", "prod"))
    _runner: object | None = None
    _searcher: object | None = None
    _client: object | None = None
    _schema: str | None = None
    searcher_checked: bool = False

    def runner(self):
        if self._runner is None:
            from jobradar.agent.tools import DatabricksRunner

            self._runner = DatabricksRunner(env=self.env)
        return self._runner

    def searcher(self):
        if self._searcher is None and not self.searcher_checked:
            self.searcher_checked = True
            from pathlib import Path

            if Path(os.environ.get("JOBRADAR_RAG_DIR", "data/rag"), "index.faiss").exists():
                from jobradar.rag.index import FastEmbedder, SearchIndex

                self._searcher = SearchIndex(FastEmbedder())
        return self._searcher

    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def schema(self) -> str:
        if self._schema is None:
            self._schema = self.runner().describe()
        return self._schema


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services()


def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("JOBRADAR_API_KEY", "")
    if not expected:
        raise HTTPException(503, "JOBRADAR_API_KEY is not set on the server; endpoint disabled")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "missing or wrong X-API-Key")


Svc = Annotated[Services, Depends(get_services)]
Key = Depends(require_key)

app = FastAPI(
    title="Job Radar API",
    version=_version(),
    description="Read-only API over Job Radar's gold tables and assistant.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": _version()}


@app.get("/jobs/today", dependencies=[Key])
def jobs_today(
    svc: Svc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    reach: Literal["Within reach", "Stretch"] | None = None,
    role_family: Literal[ROLE_FAMILIES] | None = None,  # type: ignore[valid-type]
) -> dict:
    """The Today list: new roles at sponsors, at your level, best fit first."""
    filters = []
    if reach:
        filters.append(f"reach = '{reach}'")  # value is one of two literals
    if role_family:
        filters.append(f"role_family = '{role_family}'")  # value is from ROLE_FAMILIES
    where = f"where {' and '.join(filters)}" if filters else ""
    sql = (
        f"select {TODAY_COLUMNS} from mart_new_postings {where} "
        f"order by fit_score desc nulls last, first_seen desc limit {limit}"
    )
    columns, rows = svc.runner().run(check(sql, env=svc.env).sql)
    jobs = [dict(zip(columns, r, strict=False)) for r in rows]
    return {"count": len(jobs), "jobs": jobs}


@app.get("/jobs/search", dependencies=[Key])
def jobs_search(
    svc: Svc,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    k: Annotated[int, Query(ge=1, le=10)] = 6,
    my_level_only: bool = True,
) -> dict:
    """Search job descriptions by meaning; one best passage per posting."""
    searcher = svc.searcher()
    if searcher is None:
        raise HTTPException(503, "search index not available on this server")
    hits = searcher.search(q, k=k, my_level_only=my_level_only)
    return {
        "query": q,
        "results": [
            {
                "posting_key": h.posting_key,
                "company": h.company,
                "title": h.title,
                "url": h.url,
                "location": h.location,
                "years_required": h.years_required,
                "fit_score": h.fit_score,
                "match": round(float(h.score), 4),
                "passage": h.passage,
            }
            for h in hits
        ],
    }


if os.environ.get("JOBRADAR_WATCHDOG") == "1":
    # Only on the watchdog function, which has no public URL: the Lambda Web Adapter passes
    # the daily EventBridge event here as POST /events. The public API never has this route.
    @app.post("/events", include_in_schema=False)
    def watchdog_event() -> dict:
        from dataclasses import asdict

        from jobradar.ops.watchdog import run_from_environment

        return asdict(run_from_environment())


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask", dependencies=[Key])
def ask_endpoint(body: AskIn, svc: Svc) -> dict:
    """Ask the assistant. Read-only tools; no resume on the server."""
    from jobradar.agent.assistant import DEFAULT_MODEL, ask

    if not os.environ.get("ANTHROPIC_API_KEY") and svc._client is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set on the server")
    model = os.environ.get("JOBRADAR_AGENT_MODEL") or DEFAULT_MODEL
    r = ask(
        body.question, svc.client(), svc.runner(), env=svc.env, model=model,
        schema_text=svc.schema(), searcher=svc.searcher(), resume_text=None,
    )  # fmt: skip
    return {
        "answer": r.answer,
        "model": r.model,
        "tools": [s.tool for s in r.steps if s.kind == "tool"],
        "queries": [{"detail": q["detail"], "ok": q["ok"]} for q in r.queries],
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "seconds": r.seconds,
        "stopped_early": r.stopped_early,
    }
