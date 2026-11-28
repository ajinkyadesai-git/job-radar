"""The serving layer: the gold views the website reads, published to S3 once a day.

Before, every visit sent a live query to the Databricks SQL warehouse. That tied the site's
uptime to the warehouse, and on the Free Edition the visitors' queries used up the compute
quota (the workspace was locked twice in a week). Now the daily pipeline, right after dbt
builds gold, runs these queries once and writes the answers to one small gzipped JSON file:

    s3://<bucket>/<prefix>/ops/serving/snapshot.json.gz        what the API reads
    s3://<bucket>/<prefix>/ops/serving/history/<day>.json.gz   one copy per day, for rollback

The API serves Today, Employers, Insights and resume match from that file, so the warehouse
starts once a day instead of on every visit, and the site keeps working (with the last good
data and its date) while Databricks is down. Only Ask still queries Databricks live, because
its questions can't be answered in advance.

The match ranking below repeats queries.match_sql in Python, rule for rule; the tests run both
on the same rows to keep them in step.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from jobradar.queries import (
    EMPLOYERS_SQL,
    FRESH_DAYS,
    INSIGHTS,
    MATCH_COLUMNS,
    MATCH_SMOOTHING,
    ROLE_FAMILIES,
    TODAY_COLUMNS,
)

SNAPSHOT_VERSION = 1
TODAY_ROWS = 500  # the whole Today list; filters are applied when serving
POOL_ROWS = 20_000  # far above the fresh match pool (a few thousand jobs)

# The match pool: every rule of match_sql that does not depend on the visitor.
MATCH_POOL_SQL = (
    f"select {MATCH_COLUMNS}, seniority from fct_postings "
    "where is_open and is_us and is_sponsor and is_fte_or_contract "
    "and not has_visa_blocker and not is_perm_style_ad "
    "and coalesce(role_family, 'Other') <> 'Other' "
    f"and first_seen >= date_sub(current_date(), {FRESH_DAYS}) "
    "and n_skills >= 3"
)
TODAY_ALL_SQL = (
    f"select {TODAY_COLUMNS} from mart_new_postings "
    f"order by fit_score desc nulls last, first_seen desc limit {TODAY_ROWS}"
)
DATA_AS_OF_SQL = "select max(last_seen) as data_as_of from fct_postings"


def _plain(value):
    """Values from the warehouse as JSON-friendly ones (dates as text, decimals as floats)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(run, sql: str, max_rows: int) -> list[dict]:
    columns, rows = run(sql, max_rows)
    return [{c: _plain(v) for c, v in zip(columns, r, strict=False)} for r in rows]


def build_snapshot(run, now: datetime | None = None) -> dict:
    """Run the serving queries once. `run(sql, max_rows)` returns (columns, rows) and is
    expected to pass the SQL through the guard."""
    now = now or datetime.now(UTC)
    as_of = _rows(run, DATA_AS_OF_SQL, 1)
    snap = {
        "version": SNAPSHOT_VERSION,
        "built_at": now.isoformat(timespec="seconds"),
        "as_of": (as_of[0]["data_as_of"] if as_of else None) or now.date().isoformat(),
        "today": _rows(run, TODAY_ALL_SQL, TODAY_ROWS),
        "employers": _rows(run, EMPLOYERS_SQL, 100),
        "insights": {name: _rows(run, sql, 100) for name, sql in INSIGHTS.items()},
        "match_pool": _rows(run, MATCH_POOL_SQL, POOL_ROWS),
    }
    if not snap["employers"] or not snap["match_pool"]:
        raise RuntimeError("serving snapshot is empty; not publishing it over the last good one")
    return snap


def snapshot_key(prefix: str, day: str | None = None) -> str:
    base = f"{prefix}/ops/serving" if prefix else "ops/serving"
    return f"{base}/history/{day}.json.gz" if day else f"{base}/snapshot.json.gz"


def encode(snap: dict) -> bytes:
    return gzip.compress(json.dumps(snap, separators=(",", ":")).encode())


def publish(snap: dict, s3, bucket: str, prefix: str) -> list[str]:
    """Write the dated copy first, then the one the API reads, so a failed run never leaves
    the API pointing at half a snapshot."""
    body = encode(snap)
    keys = [snapshot_key(prefix, snap["built_at"][:10]), snapshot_key(prefix)]
    for key in keys:
        s3.put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json",
            ContentEncoding="gzip", ServerSideEncryption="AES256",
        )  # fmt: skip
    return keys


@dataclass
class SnapshotStore:
    """Reads the snapshot from S3 and keeps it in memory for a few minutes per Lambda."""

    s3: object
    bucket: str
    prefix: str = "prod"
    ttl_s: float = 300
    _snap: dict | None = None
    _loaded_at: float = 0.0
    _etag: str | None = None
    _clock: object = field(default=time.monotonic)

    def get(self) -> dict | None:
        """The snapshot, or None when there is none yet. A failed refresh keeps the copy
        already in memory rather than failing the request."""
        if self._snap is not None and self._clock() - self._loaded_at < self.ttl_s:
            return self._snap
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=snapshot_key(self.prefix))
            etag = obj.get("ETag")
            if self._snap is None or etag != self._etag:
                self._snap = json.loads(gzip.decompress(obj["Body"].read()))
                self._etag = etag
        except Exception:
            if self._snap is None:
                return None
        self._loaded_at = self._clock()
        return self._snap


def store_from_environment() -> SnapshotStore | None:
    """None when no bucket is set (local runs and tests use the live warehouse)."""
    import os

    bucket = os.environ.get("JOBRADAR_S3_BUCKET")
    if not bucket or os.environ.get("JOBRADAR_SERVING", "on") == "off":
        return None
    import boto3

    return SnapshotStore(s3=boto3.client("s3"), bucket=bucket,
                         prefix=os.environ.get("JOBRADAR_S3_PREFIX", "prod"))  # fmt: skip


# --- Serving: the same answers the live queries gave ------------------------------------------


def today_rows(snap: dict, limit: int = 20, reach: str | None = None,
               role_family: str | None = None) -> list[dict]:  # fmt: skip
    """The Today list from the snapshot; it is already in best-fit-first order."""
    rows = [
        r for r in snap.get("today", [])
        if (not reach or r.get("reach") == reach)
        and (not role_family or r.get("role_family") == role_family)
    ]  # fmt: skip
    return [dict(r) for r in rows[:limit]]


def _hidden_levels(years: int) -> tuple[str, ...]:
    hidden = []
    if years < 8:
        hidden += ["Staff / principal", "Director+"]
    if years < 4:
        hidden.append("Senior")
    return tuple(hidden)


def match_rows(snap: dict, skills: list[str], years: int, role_family: str | None = None,
               limit: int = 25) -> list[dict]:  # fmt: skip
    """queries.match_sql over the snapshot's match pool, in Python."""
    from jobradar.agent.skills import SKILLS

    names = sorted(set(skills))
    if not 1 <= len(names) <= 40:
        raise ValueError("give between 1 and 40 skills")
    unknown = [n for n in names if n not in SKILLS]
    if unknown:
        raise ValueError(f"unknown skills: {unknown[:5]}")
    if role_family and (role_family not in ROLE_FAMILIES or role_family == "Other"):
        raise ValueError(f"role_family must be one of {ROLE_FAMILIES[:-1]}")
    hidden = _hidden_levels(int(years))
    kept = []
    for r in snap.get("match_pool", []):
        if (r.get("years_required") or 0) > int(years) + 2:
            continue
        # SQL's "seniority not in (...)" also drops rows with no seniority.
        if hidden and (r.get("seniority") is None or r["seniority"] in hidden):
            continue
        if role_family and r.get("role_family") != role_family:
            continue
        kept.append(r)
    # One row per company and title, newest first (the SQL's row_number() ... = 1).
    kept.sort(key=lambda r: r.get("posting_key") or "")
    kept.sort(key=lambda r: r.get("first_seen") or "", reverse=True)
    seen, unique = set(), []
    for r in kept:
        k = (r.get("company_name"), (r.get("title") or "").lower())
        if k not in seen:
            seen.add(k)
            unique.append(r)
    scored = []
    for r in unique:
        field_ = r.get("skills") or ""
        matched = sum(1 for n in names if f"|{n}|" in field_)
        if matched:
            scored.append((matched / (r["n_skills"] + MATCH_SMOOTHING), matched, r))
    scored.sort(key=lambda t: (t[0], t[1], t[2].get("first_seen") or ""), reverse=True)
    out = []
    for _, matched, r in scored[:limit]:
        row = {k: v for k, v in r.items() if k != "seniority"}
        row["matched"] = matched
        out.append(row)
    return out
