"""The serving snapshot: export, the S3 store, and the API answering from it while Databricks is
down (the lockouts of Nov 22 and Nov 26)."""

import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from jobradar.api.app import Services, app, get_services
from jobradar.serving import (
    MATCH_POOL_SQL,
    SnapshotStore,
    build_snapshot,
    encode,
    match_rows,
    publish,
    snapshot_key,
    today_rows,
)

KEY = {"X-API-Key": "test-key"}
OWNER = {**KEY, "X-Owner-Key": "owner-pass"}


def job(key, company, title, skills, n, first_seen="2026-11-20", years=None, seniority="Mid",
        family="Data / BI / AI"):  # fmt: skip
    return {
        "posting_key": key, "company_name": company, "title": title, "location": "Remote",
        "url": f"https://x/{key}", "role_family": family, "years_required": years,
        "salary_min_yearly_usd": None, "salary_max_yearly_usd": None,
        "company_lca_filings": 10, "company_median_filed_wage": 120000.0,
        "first_seen": first_seen, "skills": skills, "n_skills": n, "seniority": seniority,
    }  # fmt: skip


POOL = [
    job("a:1", "Ramp", "Data Engineer", "|Python|SQL|dbt|", 3),  # 3 of 3 -> 3/6 = 0.50
    job(
        "a:2", "Ramp", "data engineer", "|Python|SQL|dbt|", 3, first_seen="2026-11-10"
    ),  # older copy
    job(
        "b:1", "Stripe", "Analytics Engineer", "|Python|SQL|dbt|Looker|Airflow|Spark|Tableau|", 7
    ),  # 3/10
    job(
        "c:1",
        "Figma",
        "Senior Data Engineer",
        "|Python|SQL|dbt|",
        3,
        first_seen="2026-11-19",
        seniority="Senior",
    ),
    job(
        "d:1", "Notion", "Data Analyst", "|SQL|Tableau|Excel|", 3, years=6.0
    ),  # asks too many years
    job(
        "e:1", "Plaid", "Platform Engineer", "|Go|Kubernetes|AWS|", 3, family="Software"
    ),  # no overlap
    job("f:1", "Brex", "BI Engineer", "|Python|SQL|Looker|", 3, seniority=None),  # level unknown
]


def today(key, reach, family, fit):
    return {"posting_key": key, "title": key, "reach": reach, "role_family": family,
            "fit_score": fit}  # fmt: skip


INSIGHTS = {
    "jobs_by_family": [{"role_family": "Software", "open_jobs": 10, "good_fit": 2}],
    "new_per_day": [],
    "pay_by_family": [],
    "top_sponsors": [],
}
SNAP = {
    "version": 1,
    "built_at": "2026-11-25T23:40:00+00:00",
    "as_of": "2026-11-25",
    "today": [
        today("t1", "Within reach", "Software", 0.9),
        today("t2", "Stretch", "Data / BI / AI", 0.8),
        today("t3", "Within reach", "Data / BI / AI", 0.7),
    ],
    "employers": [{"company": "ramp", "company_name": "Ramp", "open_us_postings": 40}],
    "insights": INSIGHTS,
    "match_pool": POOL,
}


def test_match_follows_the_sql_rules():
    keys = [r["posting_key"] for r in match_rows(SNAP, ["Python", "SQL", "dbt"], years=3)]
    # Ramp once (the newest copy), ranked by the smoothed share; Senior hidden under 4 years;
    # too many years asked; no shared skill; and no seniority (SQL's NOT IN drops nulls).
    assert keys == ["a:1", "b:1"]
    five = [r["posting_key"] for r in match_rows(SNAP, ["Python", "SQL", "dbt"], years=5)]
    # At 5 years: Senior shows, and 6 years asked is within reach (<= 5 + 2); Brex still hidden.
    assert five == ["a:1", "c:1", "b:1", "d:1"]
    assert match_rows(SNAP, ["SQL"], years=3, role_family="Software") == []
    assert match_rows(SNAP, ["Python"], years=3)[0]["matched"] == 1
    assert "seniority" not in match_rows(SNAP, ["Python"], years=3)[0]


def test_match_refuses_what_match_sql_refuses():
    for bad in (
        lambda: match_rows(SNAP, ["SQL') or 1=1 --"], 3),
        lambda: match_rows(SNAP, [], 3),
        lambda: match_rows(SNAP, ["SQL"], 3, role_family="Other"),
    ):
        with pytest.raises(ValueError):
            bad()


def test_today_filters_keep_best_fit_order():
    assert [r["posting_key"] for r in today_rows(SNAP, limit=10)] == ["t1", "t2", "t3"]
    assert [r["posting_key"] for r in today_rows(SNAP, 10, reach="Within reach")] == ["t1", "t3"]
    assert [r["posting_key"] for r in today_rows(SNAP, 10, role_family="Data / BI / AI")] == [
        "t2",
        "t3",
    ]
    assert len(today_rows(SNAP, limit=1)) == 1


def test_export_runs_each_query_once_and_makes_plain_json():
    ran = []

    def run(sql, max_rows):
        ran.append((sql, max_rows))
        if "max(last_seen)" in sql:
            return ["data_as_of"], [(date(2026, 11, 25),)]
        if sql == MATCH_POOL_SQL:
            return ["posting_key", "first_seen", "n_skills"], [("a:1", date(2026, 11, 20), 3)]
        return ["company_name", "median_filed_wage"], [("Ramp", Decimal("120000.50"))]

    snap = build_snapshot(run, now=datetime(2026, 11, 25, 23, 40, tzinfo=UTC))
    assert snap["as_of"] == "2026-11-25"
    assert snap["match_pool"][0]["first_seen"] == "2026-11-20"
    assert snap["employers"][0]["median_filed_wage"] == 120000.5
    assert set(snap["insights"]) == {
        "jobs_by_family",
        "new_per_day",
        "pay_by_family",
        "top_sponsors",
    }
    json.dumps(snap)  # everything is JSON-ready
    assert len(ran) == 8 and max(n for _, n in ran) == 20_000


def test_export_refuses_to_publish_an_empty_snapshot():
    with pytest.raises(RuntimeError, match="empty"):
        build_snapshot(lambda sql, n: (["x"], []))


class S3:
    def __init__(self):
        self.objects, self.gets = {}, 0
        self.fail = False

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        self.gets += 1
        if self.fail or Key not in self.objects:
            raise type("NoSuchKey", (Exception,), {})()
        body = self.objects[Key]
        return {"Body": type("B", (), {"read": lambda _s: body})(), "ETag": str(hash(body))}


def test_publish_writes_a_dated_copy_then_the_latest():
    s3 = S3()
    keys = publish(SNAP, s3, "bucket", "prod")
    assert keys == [
        "prod/ops/serving/history/2026-11-25.json.gz",
        "prod/ops/serving/snapshot.json.gz",
    ]
    assert json.loads(gzip.decompress(s3.objects[snapshot_key("prod")]))["as_of"] == "2026-11-25"


def test_store_caches_and_keeps_the_last_good_copy():
    s3, now = S3(), [0.0]
    store = SnapshotStore(s3=s3, bucket="b", prefix="prod", ttl_s=300, _clock=lambda: now[0])
    assert store.get() is None  # nothing published yet: the API falls back to the warehouse
    s3.objects[snapshot_key("prod")] = encode(SNAP)
    assert store.get()["as_of"] == "2026-11-25"
    gets = s3.gets
    assert store.get() is not None and s3.gets == gets  # cached in memory
    now[0] = 1000
    s3.fail = True
    assert store.get()["as_of"] == "2026-11-25"  # S3 hiccup: keep serving what we have


class DownRunner:
    """Databricks during the lockout: every call fails."""

    def run(self, sql):
        raise RuntimeError("BAD_REQUEST: Cannot create the resource, please try again later.")

    def describe(self):
        raise RuntimeError("BAD_REQUEST: Cannot create the resource, please try again later.")


class Store:
    def __init__(self, snap):
        self.snap = snap

    def get(self):
        return self.snap


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JOBRADAR_API_KEY", "test-key")
    monkeypatch.setenv("JOBRADAR_OWNER_KEY", "owner-pass")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("JOBRADAR_S3_BUCKET", raising=False)

    def make(snap):
        s = Services(env="prod", _runner=DownRunner(), _store=Store(snap), store_checked=True,
                     quota_checked=True, usage_checked=True)  # fmt: skip
        app.dependency_overrides[get_services] = lambda: s
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_site_keeps_working_from_the_snapshot_while_databricks_is_down(client):
    c = client(SNAP)
    today = c.get("/jobs/today?reach=Within%20reach", headers=OWNER).json()
    assert [j["posting_key"] for j in today["jobs"]] == ["t1", "t3"] and today[
        "as_of"
    ] == "2026-11-25"
    assert c.get("/employers", headers=KEY).json()["employers"][0]["company_name"] == "Ramp"
    assert c.get("/insights", headers=KEY).json()["as_of"] == "2026-11-25"
    m = c.post("/match", headers=KEY, json={"skills": ["Python", "SQL", "dbt"], "years": 3}).json()
    assert [j["posting_key"] for j in m["jobs"]] == ["a:1", "b:1"]
    assert m["jobs"][0]["match_pct"] == 100 and m["jobs"][1]["missing"][0] == "Looker"


def test_ask_pauses_with_a_clear_message_when_databricks_is_down(client):
    r = client(SNAP).post("/ask", headers=KEY, json={"question": "How many jobs are open?"})
    assert r.status_code == 503 and "Ask is paused" in r.json()["detail"]


def test_no_snapshot_and_databricks_down_is_a_503_not_a_500(client):
    c = client(None)
    for path in ("/employers", "/insights"):
        r = c.get(path, headers=KEY)
        assert r.status_code == 503 and "Databricks" in r.json()["detail"]
    assert c.get("/jobs/today", headers=OWNER).status_code == 503
