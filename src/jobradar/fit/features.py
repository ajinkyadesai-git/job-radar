"""Posting features for the fit model, read from the gold layer (fct_postings)."""

from __future__ import annotations

import os
import re
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
# Company is left out on purpose: fit depends on the role, not the brand, and with few labels
# the model would memorize company names instead of learning what you look for.
CATEGORICAL = ["role_family", "seniority", "workplace_type"]
NUMERIC = [
    "years_required",
    "is_remote",
    "salary_max_yearly_usd",
    "company_lca_filings",
    "company_certified_rate",
    "company_median_filed_wage",
]


# "5+ years", "3-5 years", "7 yrs", "at least 4 years": the first number before years/yrs.
_YEARS = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years|yrs)\b", re.I)


def years_required(text: str | None) -> float | None:
    """Years of experience the posting asks for: the largest figure mentioned (capped at 20).

    Postings often say "2+ years with Python" and "5+ years overall"; the larger number is the
    bar a recruiter screens on. None when the posting gives no figure.
    """
    found = [int(m.group(1)) for m in _YEARS.finditer(text or "")]
    found = [n for n in found if 0 < n <= 20]
    return float(max(found)) if found else None


def gold_table(env: str = "prod") -> str:
    return f"workspace.{'jobradar_dev' if env == 'dev' else 'jobradar'}_gold.fct_postings"


def _connect():
    from databricks import sql

    return sql.connect(
        server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


# Same cutoff as the Today list: my_years_experience (3) + stretch_years (2) in
# dbt/dbt_project.yml. Jobs asking more years than this are not scored or queued.
MAX_YEARS_ALLOWED = 5


def fetch_candidates(env: str = "prod", connection=None) -> pd.DataFrame:
    """Open postings you could apply to: the same rules as the Today list, but not only new.

    Postings that say they won't sponsor, read like green-card ads (CR11), or ask for more
    than MAX_YEARS_ALLOWED years of experience are left out.
    """
    own = connection is None
    connection = connection or _connect()
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(FEATURE_COLUMNS)}, url FROM {gold_table(env)} "
                "WHERE is_open AND is_us AND is_fte_or_contract AND is_target_level AND is_sponsor "
                "AND NOT has_visa_blocker AND NOT is_perm_style_ad "
                f"AND coalesce(years_required, 0) <= {MAX_YEARS_ALLOWED}"
            )
            return pd.DataFrame(cur.fetchall(), columns=[*FEATURE_COLUMNS, "url"])
    finally:
        if own:
            connection.close()


def fetch_postings(keys: Iterable[str], env: str = "prod", connection=None) -> pd.DataFrame:
    """Read the feature columns for these posting keys from Databricks (read-only query)."""
    keys = sorted(set(keys))
    if not keys:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    own = connection is None
    connection = connection or _connect()
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
    out["years_required"] = out[TEXT_BODY].map(years_required)
    out[TEXT_BODY] = out[TEXT_BODY].str.slice(0, 4000)  # the start says the most
    for col in CATEGORICAL:
        out[col] = out[col].fillna("unknown").astype(str)
    for col in NUMERIC:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)
    return out
