"""Upload today's fit scores to Databricks so the assistant and the Today list can rank by them.

The model runs on your laptop (it holds your resume and labels). Only one number per posting
leaves the laptop: workspace.jobradar_ml.fit_scores(posting_key, fit_score, model_version,
scored_at). The table is replaced on each run; dbt joins it into fct_postings.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

SCORES_SCHEMA = "workspace.jobradar_ml"
SCORES_TABLE = f"{SCORES_SCHEMA}.fit_scores"
_KEY_OK = re.compile(r"^[a-z]+:[A-Za-z0-9_-]+$")
BATCH = 1000


def model_version(model_path: str | Path, n_labels: int) -> str:
    digest = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()[:10]
    return f"{digest}-l{n_labels}"


def values_sql(keys: Sequence[str], scores: Sequence[float], version: str) -> list[str]:
    """INSERT ... VALUES batches. Keys must match a strict pattern, so nothing can be injected."""
    if len(keys) != len(scores):
        raise ValueError("keys and scores differ in length")
    rows = []
    for k, s in zip(keys, scores, strict=True):
        if not _KEY_OK.match(k):
            raise ValueError(f"unexpected posting key {k!r}")
        rows.append(f"('{k}', {float(s):.6f}, '{version}', current_timestamp())")
    return [
        f"INSERT INTO {SCORES_TABLE} VALUES " + ", ".join(rows[i : i + BATCH])
        for i in range(0, len(rows), BATCH)
    ]


def upload_scores(connection, keys: Sequence[str], scores: Sequence[float], version: str) -> int:
    statements = values_sql(keys, scores, version)
    with connection.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCORES_SCHEMA}")
        cur.execute(
            f"CREATE OR REPLACE TABLE {SCORES_TABLE} ("
            "posting_key STRING NOT NULL, fit_score DOUBLE NOT NULL, "
            "model_version STRING NOT NULL, scored_at TIMESTAMP NOT NULL) "
            "COMMENT 'Fit model scores (0-1) from jobradar fit-score; replaced on each run'"
        )
        for sql in statements:
            cur.execute(sql)
    return len(keys)
