import pandas as pd
import pytest

from jobradar.ingest.dol import (
    KEPT_COLUMNS,
    LcaFileError,
    quarter_of,
    select_columns,
    upload_lca_file,
)
from jobradar.ingest.storage import LocalStorage


def _sample() -> pd.DataFrame:
    row = {c: f"v_{c}" for c in KEPT_COLUMNS}
    row.update(
        CASE_NUMBER="I-200-25280-123456",
        DECISION_DATE=pd.Timestamp("2025-10-07"),
        WAGE_RATE_OF_PAY_FROM=185000.0,
        EMPLOYER_POC_EMAIL="person@example.com",  # personal data: must be dropped
        AGENT_ATTORNEY_LAST_NAME="Doe",
    )
    return pd.DataFrame([row])


def test_quarter_from_file_name():
    q = quarter_of("/downloads/LCA_Disclosure_Data_FY2026_Q3.xlsx")
    assert (q.fiscal_year, q.quarter) == (2026, 3)
    assert q.prefix == "raw/dol/fiscal_year=2026/quarter=Q3"
    with pytest.raises(LcaFileError):
        quarter_of("lca_2026.xlsx")


def test_quarter_accepts_dol_misspelled_file_name():
    q = quarter_of("LCA_Dislclosure_Data_FY2026_Q3.xlsx")  # DOL's own spelling
    assert (q.fiscal_year, q.quarter) == (2026, 3)


def test_select_columns_keeps_business_fields_and_drops_personal_data():
    out = select_columns(_sample())

    assert list(out.columns) == [c.lower() for c in KEPT_COLUMNS]
    assert "employer_poc_email" not in out.columns
    assert "agent_attorney_last_name" not in out.columns
    assert out.loc[0, "case_number"] == "I-200-25280-123456"
    assert out.loc[0, "decision_date"].startswith("2025-10-07")
    assert out.loc[0, "wage_rate_of_pay_from"] == "185000.0"


def test_fy2026_hyphenated_header_is_read():
    df = _sample().rename(columns={"H1B_DEPENDENT": "H-1B_DEPENDENT"})
    df["H-1B_DEPENDENT"] = "Y"
    assert select_columns(df).loc[0, "h1b_dependent"] == "Y"


def test_missing_optional_column_becomes_null_but_required_must_exist():
    df = _sample().drop(columns=["NAICS_CODE"])
    assert select_columns(df).loc[0, "naics_code"] is pd.NA

    with pytest.raises(LcaFileError, match="EMPLOYER_NAME"):
        select_columns(_sample().drop(columns=["EMPLOYER_NAME"]))


def test_upload_lands_both_files_once(tmp_path):
    xlsx = tmp_path / "LCA_Disclosure_Data_FY2025_Q4.xlsx"
    xlsx.write_bytes(b"pretend excel bytes")
    store = LocalStorage(tmp_path / "lake")

    first = upload_lca_file(xlsx, store, reader=lambda _: _sample())
    second = upload_lca_file(xlsx, store, reader=lambda _: _sample())

    assert first.status == "landed" and first.rows == 1
    assert first.columns_dropped == 2
    prefix = "raw/dol/fiscal_year=2025/quarter=Q4"
    assert store.exists(f"{prefix}/LCA_Disclosure_Data_FY2025_Q4.xlsx")
    parquet = pd.read_parquet(tmp_path / "lake" / prefix / "lca_selected.parquet")
    assert "employer_poc_email" not in parquet.columns
    assert second.status == "unchanged"


def test_cli_dol_upload_to_local(tmp_path, monkeypatch):
    from jobradar import cli
    from jobradar.ingest import dol

    xlsx = tmp_path / "LCA_Disclosure_Data_FY2026_Q1.xlsx"
    xlsx.write_bytes(b"pretend excel bytes")
    monkeypatch.setattr(dol, "read_lca_xlsx", lambda _: _sample())
    monkeypatch.setattr(dol.upload_lca_file, "__defaults__", (dol.read_lca_xlsx,))
    monkeypatch.setenv("JOBRADAR_LOCAL_ROOT", str(tmp_path / "lake"))

    assert cli.main(["dol-upload", "--dest", "local", str(xlsx)]) == 0
    assert (tmp_path / "lake/raw/dol/fiscal_year=2026/quarter=Q1/lca_selected.parquet").exists()
