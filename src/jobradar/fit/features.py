"""Posting features for the fit model, read from the gold layer (fct_postings)."""

from __future__ import annotations

import os
from collections.abc import Iterable

import pandas as pd

FEATURE_COLUMNS = [
    "posting_key",
    "company",
    "title",
    "location",
    "role_family",
    "seniority",
    "workplace_type",
    "employment_type",
    "is_remote",
    "is_us",
    "salary_max_yearly_usd",
    "company_lca_filings",
    "company_certified_rate",
    "company_median_filed_wage",
    "description_text",
]
TEXT_TITLE, TEXT_BODY = "title", "description_text"
CATEGORICAL = ["role_family", "seniority", "workplace_type", "company"]
NUMERIC = [
    "is_remote",
    "salary_max_yearly_usd",
    "company_lca_filings",
    "company_certified_rate",
    "company_median_filed_wage",
]


def gold_table(env: str = "prod") -> str:
    return f"workspace.{'jobradar_dev' if env == 'dev' else 'jobradar'}_gold.fct_postings"


def fetch_postings(keys: Iterable[str], env: str = "prod", connection=None) -> pd.DataFrame:
    """Read the feature columns for these posting keys from Databricks (read-only query)."""
    keys = sorted(set(keys))
    if not keys:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    own = connection is None
    if own:
        from databricks import sql

        connection = sql.connect(
            server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        )
    try:
        frames = []
        with connection.cursor() as cur:
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                marks = ", ".join(["?"] * len(chunk))
                cur.execute(
                    f"SELECT {', '.join(FEATURE_COLUMNS)} FROM {gold_table(env)} "
                    f"WHERE posting_key IN ({marks})",
                    chunk,
                )
                frames.append(pd.DataFrame(cur.fetchall(), columns=FEATURE_COLUMNS))
        return pd.concat(frames, ignore_index=True)
    finally:
        if own:
            connection.close()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Fill gaps so every row can be scored: empty text, 'unknown' categories, numbers as float."""
    out = df.copy()
    for col in (TEXT_TITLE, TEXT_BODY):
        out[col] = out[col].fillna("").astype(str)
    out[TEXT_BODY] = out[TEXT_BODY].str.slice(0, 4000)  # the start says the most
    for col in CATEGORICAL:
        out[col] = out[col].fillna("unknown").astype(str)
    for col in NUMERIC:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)
    return out
