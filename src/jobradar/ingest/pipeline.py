"""Daily ingest: pull each enabled board once, land changed responses in the raw zone,
and write one run-log row per company plus one summary row.

Idempotency: a response is identified by the SHA-256 of its canonical JSON. If it matches
the last landed hash for that board, nothing is written to raw/ or state/; the run log
records status "unchanged" with a pointer to the object already landed. Running twice
on the same day therefore changes nothing in the data zones.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

import requests

from jobradar.config import Company
from jobradar.ingest.boards import ADAPTERS, BoardContractError
from jobradar.ingest.http import PoliteClient
from jobradar.ingest.storage import Storage, get_json, put_json

log = logging.getLogger(__name__)

PIPELINE = "ingest_job_boards"
Status = Literal["landed", "unchanged", "failed"]


def canonical_sha256(payload: Any) -> str:
    """Hash of the parsed JSON with sorted keys, so whitespace or key order can't fake a change."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def raw_key(company: Company, load_date: date, sha: str) -> str:
    return (
        f"raw/{company.source.value}/{company.slug}/"
        f"load_date={load_date.isoformat()}/{sha[:16]}.json"
    )


def state_key(company: Company) -> str:
    return f"state/{company.source.value}/{company.slug}.json"


def runlog_key(run_date: date, run_id: str) -> str:
    return f"ops/pipeline_runs/run_date={run_date.isoformat()}/run_id={run_id}.jsonl"


@dataclass
class RunRow:
    """One row of ops.pipeline_runs. Loaded into a Delta table in week 2."""

    run_id: str
    pipeline: str
    stage: str
    source: str | None
    company: str | None
    status: Status | Literal["success", "partial", "failed_all"]
    started_at: str
    finished_at: str
    duration_ms: int
    http_status: int | None = None
    attempts: int | None = None
    job_count: int | None = None
    bytes: int | None = None
    content_sha256: str | None = None
    object_uri: str | None = None
    new_fields: list[str] = field(default_factory=list)
    error_type: str | None = None
    error: str | None = None
    load_date: str | None = None
    env: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def ingest_company(
    company: Company, client: PoliteClient, store: Storage, load_date: date, run_id: str, env: str
) -> RunRow:
    adapter = ADAPTERS[company.source]
    url, params = adapter.url(company)
    started = _now()
    t0 = time.monotonic()
    row = RunRow(
        run_id=run_id,
        pipeline=PIPELINE,
        stage="fetch_board",
        source=company.source.value,
        company=company.slug,
        status="failed",
        started_at=started.isoformat(),
        finished_at="",
        duration_ms=0,
        load_date=load_date.isoformat(),
        env=env,
    )

    def done(**kw: Any) -> RunRow:
        for k, v in kw.items():
            setattr(row, k, v)
        row.finished_at = _now().isoformat()
        row.duration_ms = int((time.monotonic() - t0) * 1000)
        return row

    try:
        res = client.get(url, params=params)
    except requests.RequestException as exc:
        return done(error_type="network", error=str(exc)[:500])

    row.http_status, row.attempts, row.bytes = res.status, res.attempts, len(res.body)
    if res.status == 404:
        # Usually means the company switched job-board vendors or renamed its board.
        return done(error_type="board_not_found", error=f"404 from {url}")
    if res.status != 200:
        return done(error_type="http_error", error=f"HTTP {res.status} from {url}")

    try:
        payload = json.loads(res.body)
    except json.JSONDecodeError as exc:
        return done(error_type="invalid_json", error=str(exc)[:500])

    try:
        job_count, new_fields = adapter.validate(payload)
    except BoardContractError as exc:
        return done(error_type="contract", error=str(exc)[:500])

    row.job_count, row.new_fields = job_count, new_fields
    if new_fields:
        log.warning("%s/%s: new job fields %s", company.source, company.slug, new_fields)

    sha = canonical_sha256(payload)
    row.content_sha256 = sha
    previous = get_json(store, state_key(company))
    if previous and previous.get("content_sha256") == sha:
        return done(status="unchanged", object_uri=previous.get("object_uri"))

    key = raw_key(company, load_date, sha)
    if not store.exists(key):
        store.put_bytes(
            key,
            res.body,
            "application/json",
            metadata={
                "source": company.source.value,
                "company": company.slug,
                "content-sha256": sha,
                "job-count": str(job_count),
                "fetched-at": started.isoformat(),
                "run-id": run_id,
            },
        )
    uri = store.uri(key)
    put_json(
        store,
        state_key(company),
        {
            "content_sha256": sha,
            "object_uri": uri,
            "raw_key": key,
            "load_date": load_date.isoformat(),
            "job_count": job_count,
            "landed_at": _now().isoformat(),
            "run_id": run_id,
        },
    )
    return done(status="landed", object_uri=uri)


@dataclass
class RunSummary:
    run_id: str
    rows: list[RunRow]
    runlog_uri: str

    @property
    def counts(self) -> Counter[str]:
        return Counter(r.status for r in self.rows)

    @property
    def ok(self) -> bool:
        return self.counts.get("failed", 0) == 0


def run_ingest(
    companies: list[Company],
    client: PoliteClient,
    store: Storage,
    env: str = "dev",
    load_date: date | None = None,
    run_id: str | None = None,
) -> RunSummary:
    run_id = run_id or f"{_now():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    load_date = load_date or _now().date()
    started = _now()
    t0 = time.monotonic()

    rows: list[RunRow] = []
    for company in companies:
        row = ingest_company(company, client, store, load_date, run_id, env)
        log.info(
            "%-10s %-24s %-9s jobs=%s %s",
            row.source,
            row.company,
            row.status,
            row.job_count,
            row.error_type or "",
        )
        rows.append(row)

    counts = Counter(r.status for r in rows)
    failed = counts.get("failed", 0)
    overall = "success" if failed == 0 else ("failed_all" if failed == len(rows) else "partial")
    summary = RunRow(
        run_id=run_id,
        pipeline=PIPELINE,
        stage="summary",
        source=None,
        company=None,
        status=overall,
        started_at=started.isoformat(),
        finished_at=_now().isoformat(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        job_count=sum(r.job_count or 0 for r in rows),
        load_date=load_date.isoformat(),
        env=env,
        error=json.dumps(dict(counts), sort_keys=True),
    )

    key = runlog_key(started.date(), run_id)
    body = "\n".join(json.dumps(asdict(r), sort_keys=True) for r in [*rows, summary]) + "\n"
    store.put_bytes(key, body.encode(), "application/x-ndjson")
    return RunSummary(run_id=run_id, rows=rows, runlog_uri=store.uri(key))
