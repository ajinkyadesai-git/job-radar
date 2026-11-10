"""Read your labels exported from the private "Seed Labels" sheet (Daily Labels tab).

Export: File > Download > Comma-separated values (current sheet), saved as
data/labels/daily_labels.csv. data/ is git-ignored, so labels never reach GitHub.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

# Sheet header -> our column name.
COLUMNS = {
    "Date labeled": "label_date",
    "Source": "source",
    "Posting ID": "posting_id",
    "Company": "company",
    "Job title": "title",
    "Location": "location",
    "Job link": "url",
    "Role family": "role_family",
    "Label": "label",
    "Note": "note",
}
APPLY, SKIP = "Would apply", "Would skip"


class LabelFileError(ValueError):
    pass


def read_labels(path: str | Path) -> pd.DataFrame:
    """One row per labeled posting: posting_key, label_date, y (1 = would apply), note.

    Rows without a label are skipped (not labeled yet). If a posting was labeled twice, the
    latest label wins.
    """
    raw = pd.read_csv(path, dtype=str).rename(columns=lambda c: str(c).strip())
    missing = [c for c in ("Date labeled", "Source", "Posting ID", "Label") if c not in raw]
    if missing:
        raise LabelFileError(f"{path}: missing columns {missing}; export the Daily Labels tab")
    df = raw.rename(columns=COLUMNS)
    df = df[[c for c in COLUMNS.values() if c in df.columns]]
    df = df.dropna(subset=["source", "posting_id"])
    df["label"] = df["label"].fillna("").str.strip()
    unknown = sorted(set(df["label"]) - {APPLY, SKIP, ""})
    if unknown:
        raise LabelFileError(f"unexpected labels {unknown}; use '{APPLY}' or '{SKIP}'")
    df = df[df["label"] != ""].copy()
    df["label_date"] = pd.to_datetime(df["label_date"], errors="raise").dt.date
    df["source"] = df["source"].str.strip().str.lower()
    df["posting_id"] = df["posting_id"].str.strip()
    df["posting_key"] = df["source"] + ":" + df["posting_id"]
    df["y"] = (df["label"] == APPLY).astype(int)
    df = df.sort_values("label_date").drop_duplicates("posting_key", keep="last")
    keep = ["posting_key", "label_date", "y", "role_family", "note"]
    return df[[c for c in keep if c in df]].reset_index(drop=True)


def time_split(labels: pd.DataFrame, test_from: date | None = None):
    """Train on earlier labeling days, test on the latest day (or days from test_from on).

    A random split would let the model see postings from the same day in training and test;
    splitting by time is closer to real use: label today, predict tomorrow.
    """
    days = sorted(labels["label_date"].unique())
    if len(days) < 2:
        raise LabelFileError("need labels from at least two days for a time-based split")
    cut = test_from or days[-1]
    train = labels[labels["label_date"] < cut]
    test = labels[labels["label_date"] >= cut]
    if train.empty or test.empty:
        raise LabelFileError(f"split at {cut} leaves an empty train or test set")
    return train.reset_index(drop=True), test.reset_index(drop=True)
