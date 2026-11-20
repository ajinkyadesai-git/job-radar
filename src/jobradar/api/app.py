"""Job Radar API: the Today list, description search and the assistant over HTTP.

    GET  /health          is the service up (no key, no database call; used by deploy checks)
    GET  /jobs/today      the Today list, best fit first, with optional filters
    GET  /jobs/search     search job descriptions by meaning
    GET  /employers       the tracked companies: open jobs and H-1B record
    GET  /insights        numbers for the web app's charts (cached for an hour)
    GET  /skills          the tracked skill list and patterns (the browser reads resumes with it)
    POST /match           fresh jobs ranked for a visitor's skill names and years (CR09)
    POST /ask             ask the assistant a question (costs API money; capped per day)

Everything except /health needs the header X-API-Key matching JOBRADAR_API_KEY. If that
variable is not set, those endpoints answer 503 rather than run open to the internet.

The owner's own view (the Today list ranked by their fit model) also needs X-Owner-Key
matching JOBRADAR_OWNER_KEY: the web app is public, the owner's job search is not. Without
it, /ask runs in public mode and cannot read the Today list or fit scores.
On Lambda the secrets come from SSM Parameter Store (see load_secrets_from_ssm).

The server never sees the resume: resume_fit is a laptop-only tool, so /ask offers the
assistant run_sql, salary_check and (when an index is present) search_job_text.
"""

from __future__ import annotations

import hmac
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from jobradar.agent.sql_guard import check
from jobradar.queries import (
    EMPLOYERS_SQL,
    INSIGHTS,
    MAX_MATCH_SKILLS,
    ROLE_FAMILIES,
    match_sql,
    today_sql,
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
    _quota: object | None = None
    quota_checked: bool = False
    insights_cache: tuple[float, dict] | None = None

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

    def quota(self):
        if self._quota is None and not self.quota_checked:
            self.quota_checked = True
            from jobradar.api.quota import quota_from_environment

            self._quota = quota_from_environment()
        return self._quota

    def rows(self, sql: str) -> list[dict]:
        columns, rows = self.runner().run(check(sql, env=self.env).sql)
        return [dict(zip(columns, r, strict=False)) for r in rows]


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services()


def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("JOBRADAR_API_KEY", "")
    if not expected:
        raise HTTPException(503, "JOBRADAR_API_KEY is not set on the server; endpoint disabled")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "missing or wrong X-API-Key")


def is_owner(x_owner_key: str | None) -> bool:
    expected = os.environ.get("JOBRADAR_OWNER_KEY", "")
    return bool(expected and x_owner_key and hmac.compare_digest(x_owner_key, expected))


def require_owner(x_owner_key: Annotated[str | None, Header()] = None) -> None:
    if not os.environ.get("JOBRADAR_OWNER_KEY"):
        raise HTTPException(503, "the owner view is not set up (JOBRADAR_OWNER_KEY)")
    if not is_owner(x_owner_key):
        time.sleep(1)  # slows down guessing
        raise HTTPException(401, "owner passphrase missing or wrong")


Svc = Annotated[Services, Depends(get_services)]
Key = Depends(require_key)
Owner = Depends(require_owner)

app = FastAPI(
    title="Job Radar API",
    version=_version(),
    description="Read-only API over Job Radar's gold tables and assistant.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": _version()}


@app.get("/me", dependencies=[Key, Owner])
def me() -> dict:
    """Checks the owner passphrase (the web app's unlock box)."""
    return {"owner": True}


@app.get("/jobs/today", dependencies=[Key, Owner])
def jobs_today(
    svc: Svc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    reach: Literal["Within reach", "Stretch"] | None = None,
    role_family: Literal[ROLE_FAMILIES] | None = None,  # type: ignore[valid-type]
) -> dict:
    """The Today list: new roles at sponsors, at your level, best fit first."""
    sql = today_sql(limit, reach, role_family)
    columns, rows = svc.runner().run(check(sql, env=svc.env).sql)
    jobs = [dict(zip(columns, r, strict=False)) for r in rows]
    return {"count": len(jobs), "jobs": jobs}


@app.get("/jobs/search", dependencies=[Key, Owner])
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


@app.get("/employers", dependencies=[Key])
def employers(svc: Svc) -> dict:
    """Every tracked company: open US jobs and its H-1B filing record."""
    rows = svc.rows(EMPLOYERS_SQL)
    return {"count": len(rows), "employers": rows}


INSIGHTS_TTL_S = 3600  # the data changes once a day


@app.get("/insights", dependencies=[Key])
def insights(svc: Svc) -> dict:
    """Numbers for the web app's charts. Cached per server for an hour."""
    if svc.insights_cache and time.time() - svc.insights_cache[0] < INSIGHTS_TTL_S:
        return svc.insights_cache[1]
    data = {name: svc.rows(sql) for name, sql in INSIGHTS.items()}
    svc.insights_cache = (time.time(), data)
    return data


@app.get("/skills", dependencies=[Key])
def skills() -> dict:
    """The fixed skill list. The web app finds these in a resume inside the visitor's browser,
    so the resume itself is never sent; only the matched names are."""
    from jobradar.agent.skills import IMPLIES, SKILLS

    return {
        "skills": [{"name": n, "pattern": p} for n, p in SKILLS.items()],
        "implies": {k: list(v) for k, v in IMPLIES.items()},
    }


class MatchIn(BaseModel):
    skills: list[str] = Field(min_length=1, max_length=MAX_MATCH_SKILLS)
    years: int = Field(ge=0, le=30)
    role_family: Literal[tuple(f for f in ROLE_FAMILIES if f != "Other")] | None = None  # type: ignore[valid-type]
    limit: int = Field(default=25, ge=1, le=50)


def _reach(years_required, years: int) -> str:
    if years_required is None:
        return "Not stated"
    if float(years_required) <= years:
        return "Within reach"
    return "Stretch"


@app.post("/match", dependencies=[Key])
def match(body: MatchIn, svc: Svc) -> dict:
    """Fresh tech jobs (last 14 days) at H-1B sponsors, ranked by how many of each job's
    skills the visitor has. Nothing about the visitor is stored or logged."""
    try:
        sql = match_sql(body.skills, body.years, body.role_family, body.limit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    have = set(body.skills)
    jobs = []
    for row in svc.rows(sql):
        asked = [s for s in (row.pop("skills") or "").strip("|").split("|") if s]
        row.pop("matched", None)
        row.pop("n_skills", None)
        matched = [s for s in asked if s in have]
        row.update(
            match_pct=round(100 * len(matched) / len(asked)) if asked else 0,
            matched=matched,
            missing=[s for s in asked if s not in have],
            reach=_reach(row.get("years_required"), body.years),
        )
        jobs.append(row)
    return {"count": len(jobs), "fresh_days": 14, "jobs": jobs}


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
def ask_endpoint(
    body: AskIn, svc: Svc, x_owner_key: Annotated[str | None, Header()] = None
) -> dict:
    """Ask the assistant. Read-only tools; no resume on the server. Visitors get public mode
    (no Today list, no fit scores); the owner, with the passphrase, gets everything."""
    from jobradar.agent.assistant import DEFAULT_MODEL, ask

    if not os.environ.get("ANTHROPIC_API_KEY") and svc._client is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set on the server")
    remaining = None
    quota = svc.quota()
    if quota is not None:
        allowed, remaining = quota.take()
        if not allowed:
            raise HTTPException(429, "The daily question limit is reached; try again tomorrow.")
    model = os.environ.get("JOBRADAR_AGENT_MODEL") or DEFAULT_MODEL
    r = ask(
        body.question, svc.client(), svc.runner(), env=svc.env, model=model,
        schema_text=svc.schema(), searcher=svc.searcher(), resume_text=None,
        public=not is_owner(x_owner_key),
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
        "questions_left_today": remaining,
    }
