from datetime import date

import numpy as np
import pandas as pd
import pytest

from jobradar.fit.labels import LabelFileError, read_labels, time_split
from jobradar.fit.model import baseline_predict, score, train_and_evaluate

HEADER = (
    "Date labeled,Source,Posting ID,Company,Job title,Location,Job link,Role family,Label,Note\n"
)


def write(tmp_path, rows):
    p = tmp_path / "labels.csv"
    p.write_text(HEADER + "\n".join(rows) + "\n")
    return p


def test_read_labels_maps_apply_skip_and_skips_blank(tmp_path):
    p = write(
        tmp_path,
        [
            "2026-11-06,ashby,a1,openai,Data Engineer,SF,u,Data / BI / AI,Would apply,",
            "2026-11-06,Greenhouse,g1,stripe,Account Executive,NY,u,Other,Would skip,sales",
            "2026-11-07,ashby,a2,ramp,Analyst,NY,u,Data / BI / AI,,",
        ],
    )
    df = read_labels(p)
    assert list(df["posting_key"]) == ["ashby:a1", "greenhouse:g1"]
    assert list(df["y"]) == [1, 0]


def test_read_labels_latest_label_wins(tmp_path):
    p = write(
        tmp_path,
        [
            "2026-11-06,ashby,a1,openai,Data Engineer,SF,u,Data / BI / AI,Would skip,",
            "2026-11-07,ashby,a1,openai,Data Engineer,SF,u,Data / BI / AI,Would apply,changed mind",
        ],
    )
    df = read_labels(p)
    assert len(df) == 1 and df.loc[0, "y"] == 1


def test_read_labels_rejects_unknown_label(tmp_path):
    p = write(tmp_path, ["2026-11-06,ashby,a1,openai,T,SF,u,Other,Maybe,"])
    with pytest.raises(LabelFileError):
        read_labels(p)


def test_time_split_holds_out_last_day():
    df = pd.DataFrame(
        {
            "posting_key": ["a", "b", "c"],
            "label_date": [date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)],
            "y": [1, 0, 1],
        }
    )
    train, test = time_split(df)
    assert list(train["posting_key"]) == ["a", "b"] and list(test["posting_key"]) == ["c"]
    with pytest.raises(LabelFileError):
        time_split(df.iloc[:1])


def test_score_and_baseline():
    s = score(np.array([1, 0, 1, 0]), np.array([1, 1, 0, 0]), np.array([0.9, 0.8, 0.2, 0.1]))
    assert s.precision == 0.5 and s.recall == 0.5 and s.positives == 2
    fam = pd.DataFrame({"role_family": ["Software", "Other"]})
    assert list(baseline_predict(fam)) == [1, 0]


def synthetic(n=60):
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        good = i % 2 == 0
        rows.append(
            {
                "posting_key": f"ashby:{i}",
                "label_date": date(2026, 11, 6) if i < 40 else date(2026, 11, 7),
                "y": int(good),
                "company": "acme",
                "title": "Senior Data Engineer" if good else "Account Executive",
                "location": "San Francisco, CA",
                "role_family": "Data / BI / AI" if good else "Other",
                "seniority": "Senior",
                "workplace_type": None,
                "employment_type": "FullTime",
                "is_remote": False,
                "is_us": True,
                "salary_max_yearly_usd": float(rng.integers(120, 220) * 1000) if good else None,
                "company_lca_filings": 500,
                "company_certified_rate": 0.97,
                "company_median_filed_wage": 160000.0,
                "description_text": "spark dbt sql pipelines"
                if good
                else "quota pipeline sales crm",
            }
        )
    return pd.DataFrame(rows)


def test_train_and_evaluate_learns_an_easy_pattern(tmp_path):
    data = synthetic()
    train, test = time_split(data[["posting_key", "label_date", "y"]])
    pipe, report = train_and_evaluate(data, train["posting_key"], test["posting_key"])
    assert report.n_train == 40 and report.n_test == 20
    assert report.model.precision == 1.0 and report.model.recall == 1.0
    assert any("data" in t for t in report.top_apply_terms)
    assert pipe.predict_proba(data.drop(columns=["y"]).head(2))[:, 1].shape == (2,)
