"""Land DOL OFLC LCA disclosure files (H-1B, H-1B1, E-3) in the raw zone.

DOL blocks scripted downloads, so the quarterly Excel files are downloaded in a browser from
https://www.dol.gov/agencies/eta/foreign-labor/performance and passed to this module.

For each file it writes two objects:

    raw/dol/fiscal_year=YYYY/quarter=Qn/LCA_Disclosure_Data_FYYYYY_Qn.xlsx  # unchanged
    raw/dol/fiscal_year=YYYY/quarter=Qn/lca_selected.parquet               # columns we use

The parquet copy keeps only business fields. Contact names, emails and phone numbers of
employer staff, agents and attorneys are in the public file but are never copied, so they
never reach Databricks. A state file holds the Excel file's hash, so uploading the same file
twice writes nothing.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from jobradar.ingest.storage import Storage, get_json, put_json

FILE_RE = re.compile(r"LCA_Disclosure_Data_FY(\d{4})_Q([1-4])\.xlsx$", re.IGNORECASE)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "CASE_NUMBER",
    "CASE_STATUS",
    "DECISION_DATE",
    "VISA_CLASS",
    "JOB_TITLE",
    "SOC_CODE",
    "EMPLOYER_NAME",
    "WAGE_RATE_OF_PAY_FROM",
    "WAGE_UNIT_OF_PAY",
    "WORKSITE_STATE",
)
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "RECEIVED_DATE",
    "SOC_TITLE",
    "FULL_TIME_POSITION",
    "BEGIN_DATE",
    "END_DATE",
    "TOTAL_WORKER_POSITIONS",
    "NEW_EMPLOYMENT",
    "CONTINUED_EMPLOYMENT",
    "CHANGE_EMPLOYER",
    "TRADE_NAME_DBA",
    "EMPLOYER_CITY",
    "EMPLOYER_STATE",
    "EMPLOYER_POSTAL_CODE",
    "NAICS_CODE",
    "WORKSITE_CITY",
    "WORKSITE_COUNTY",
    "WORKSITE_POSTAL_CODE",
    "WAGE_RATE_OF_PAY_TO",
    "PREVAILING_WAGE",
    "PW_UNIT_OF_PAY",
    "PW_WAGE_LEVEL",
    "H1B_DEPENDENT",
    "WILLFUL_VIOLATOR",
)
KEPT_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class LcaFileError(ValueError):
    pass


@dataclass(frozen=True)
class LcaQuarter:
    fiscal_year: int
    quarter: int

    @property
    def prefix(self) -> str:
        return f"raw/dol/fiscal_year={self.fiscal_year}/quarter=Q{self.quarter}"

    @property
    def state_key(self) -> str:
        return f"state/dol/lca_fy{self.fiscal_year}_q{self.quarter}.json"


def quarter_of(path: str | Path) -> LcaQuarter:
    m = FILE_RE.search(Path(path).name)
    if not m:
        raise LcaFileError(
            f"{Path(path).name}: expected a name like LCA_Disclosure_Data_FY2026_Q3.xlsx"
        )
    return LcaQuarter(int(m.group(1)), int(m.group(2)))


def select_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the business columns as strings; fail if a required column is missing."""
    df = df.rename(columns=lambda c: str(c).strip().upper())
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise LcaFileError(f"file layout changed: missing required columns {missing}")
    out = pd.DataFrame(index=df.index)
    for col in KEPT_COLUMNS:
        if col in df.columns:
            values = df[col]
            out[col.lower()] = values.where(values.notna(), None).map(
                lambda v: None if v is None else str(v).strip() or None
            )
        else:
            out[col.lower()] = None
    return out.astype("string").reset_index(drop=True)


def read_lca_xlsx(path: Path) -> pd.DataFrame:
    # calamine reads large Excel files several times faster than openpyxl.
    return pd.read_excel(path, engine="calamine", dtype=object)


@dataclass
class LcaUploadResult:
    file: str
    fiscal_year: int
    quarter: int
    status: str  # landed or unchanged
    rows: int | None = None
    columns_dropped: int | None = None
    xlsx_uri: str | None = None
    parquet_uri: str | None = None


def upload_lca_file(
    path: str | Path,
    store: Storage,
    reader: Callable[[Path], pd.DataFrame] = read_lca_xlsx,
) -> LcaUploadResult:
    path = Path(path)
    q = quarter_of(path)
    body = path.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    state = get_json(store, q.state_key) or {}
    if state.get("sha256") == sha:
        return LcaUploadResult(path.name, q.fiscal_year, q.quarter, "unchanged")

    raw = reader(path)
    selected = select_columns(raw)
    buf = io.BytesIO()
    selected.to_parquet(buf, index=False)

    xlsx_key = f"{q.prefix}/{path.name}"
    parquet_key = f"{q.prefix}/lca_selected.parquet"
    store.put_bytes(
        xlsx_key,
        body,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        {"sha256": sha},
    )
    store.put_bytes(parquet_key, buf.getvalue(), "application/vnd.apache.parquet")
    put_json(store, q.state_key, {"sha256": sha, "file": path.name, "rows": len(selected)})
    return LcaUploadResult(
        path.name,
        q.fiscal_year,
        q.quarter,
        "landed",
        rows=len(selected),
        columns_dropped=sum(str(c).strip().upper() not in KEPT_COLUMNS for c in raw.columns),
        xlsx_uri=store.uri(xlsx_key),
        parquet_uri=store.uri(parquet_key),
    )
