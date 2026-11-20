"""Usage counts and feedback (CR19): counts only, no personal data, owner-only report."""

from datetime import UTC, datetime

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from jobradar.api.app import Services, app, get_services
from jobradar.api.usage import MAX_EVENTS_PER_DAY, UsageLog, clean_referrer

KEY = {"X-API-Key": "test-key"}
OWNER = {**KEY, "X-Owner-Key": "owner-pass"}
NOW = datetime(2026, 11, 20, 18, 30, tzinfo=UTC)


@pytest.fixture
def log():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="usage-test")
        yield UsageLog(s3=s3, bucket="usage-test", prefix="prod")


@pytest.mark.parametrize(
    "raw, host",
    [
        ("https://www.linkedin.com/feed/?trk=abc&email=a@b.com", "linkedin.com"),
        ("https://m.facebook.com/story.php?id=1", "facebook.com"),
        ("t.co", "t.co"),
        (None, "direct"),
        ("", "direct"),
        ("javascript:alert(1)", "other"),
        ("https://" + "a" * 70 + ".com/", "other"),
    ],
)
def test_referrers_keep_only_the_site_name(raw, host):
    assert clean_referrer(raw) == host


def test_counts_events_and_referrer_sites_per_day(log):
    log.add("visit", "https://www.linkedin.com/feed/?x=1", now=NOW)
    log.add("visit", None, now=NOW)
    log.add("match", now=NOW)
    assert not log.add("not-an-event", now=NOW)
    day = log.day("2026-11-20")
    assert day["events"] == {"visit": 2, "match": 1}
    assert day["referrers"] == {"linkedin.com": 1, "direct": 1}
    assert [d["day"] for d in log.recent_days(2, now=NOW)] == ["2026-11-20", "2026-11-19"]


def test_daily_cap_stops_counting(log):
    log.s3.put_object(
        Bucket="usage-test",
        Key="prod/ops/usage/2026-11-20.json",
        Body=f'{{"events": {{"visit": {MAX_EVENTS_PER_DAY}}}}}'.encode(),
    )
    assert not log.add("visit", now=NOW)


def test_feedback_is_saved_and_listed_newest_first(log):
    assert log.add_feedback("Please add Seattle filter", "today", now=NOW)
    later = datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
    assert log.add_feedback("Love the resume match", None, now=later)
    items = log.recent_feedback()
    assert [i["message"] for i in items] == ["Love the resume match", "Please add Seattle filter"]
    assert set(items[0]) == {"at", "page", "message"}  # nothing about the sender
    assert log.day("2026-11-20")["events"]["feedback"] == 2


@pytest.fixture
def api(monkeypatch, log):
    monkeypatch.setenv("JOBRADAR_API_KEY", "test-key")
    monkeypatch.setenv("JOBRADAR_OWNER_KEY", "owner-pass")
    s = Services(env="prod", _usage=log)
    app.dependency_overrides[get_services] = lambda: s
    yield TestClient(app)
    app.dependency_overrides.clear()


def _today(log):
    return log.day(datetime.now(UTC).date().isoformat())


def test_track_counts_visitors_but_not_the_owner(api, log):
    visit = {"event": "visit", "referrer": "https://t.co/x"}
    assert api.post("/track", json=visit, headers=KEY).status_code == 200
    assert api.post("/track", json={"event": "tab:ask"}, headers=KEY).status_code == 200
    assert api.post("/track", json={"event": "visit"}, headers=OWNER).status_code == 200
    assert api.post("/track", json={"event": "match"}, headers=KEY).status_code == 422
    assert api.post("/track", json={"event": "visit"}).status_code == 401
    day = _today(log)
    assert day["events"] == {"visit": 1, "tab:ask": 1}
    assert day["referrers"] == {"t.co": 1}


def test_feedback_endpoint_and_owner_only_report(api):
    note = {"message": "Nice!", "page": "ask"}
    assert api.post("/feedback", json=note, headers=KEY).status_code == 200
    assert api.post("/feedback", json={"message": "x"}, headers=KEY).status_code == 422
    assert api.get("/usage", headers=KEY).status_code == 401
    report = api.get("/usage?days=3", headers=OWNER).json()
    assert len(report["days"]) == 3
    assert report["feedback"][0]["message"] == "Nice!"
    assert report["days"][0]["events"]["feedback"] == 1
