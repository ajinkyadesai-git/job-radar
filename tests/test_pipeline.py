from __future__ import annotations

import json
from datetime import date

import boto3
import pytest
import responses
from moto import mock_aws

from jobradar.ingest.pipeline import canonical_sha256, raw_key, run_ingest
from jobradar.ingest.storage import LocalStorage, S3Storage
from tests.conftest import ASHBY_URL, GH_URL, fixture_json

DAY = date(2026, 10, 26)


def _mock_boards(gh: dict | None = None, ashby: dict | None = None) -> None:
    responses.get(GH_URL, json=gh or fixture_json("greenhouse_board.json"))
    responses.get(ASHBY_URL, json=ashby or fixture_json("ashby_board.json"))


def _files(root) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "ops/" not in str(p.relative_to(root))
    }


@responses.activate
def test_first_run_lands_raw_json_and_state(tmp_path, client, gh_company, ashby_company):
    _mock_boards()
    store = LocalStorage(tmp_path)

    summary = run_ingest([gh_company, ashby_company], client, store, load_date=DAY)

    assert summary.ok
    assert summary.counts == {"landed": 2}
    gh_row = summary.rows[0]
    assert gh_row.job_count == 2 and gh_row.http_status == 200 and gh_row.new_fields == []
    landed = tmp_path / raw_key(gh_company, DAY, gh_row.content_sha256)
    assert "load_date=2026-10-26" in str(landed)
    # The raw body is stored byte-for-byte as the API returned it.
    assert json.loads(landed.read_bytes()) == fixture_json("greenhouse_board.json")
    # Params we depend on were sent.
    assert "content=true" in responses.calls[0].request.url
    assert "includeCompensation=true" in responses.calls[1].request.url


@responses.activate
def test_second_run_same_day_changes_nothing(tmp_path, client, gh_company, ashby_company):
    """Week 1 done check: running it twice the same day changes nothing."""
    _mock_boards()
    _mock_boards()
    store = LocalStorage(tmp_path)

    run_ingest([gh_company, ashby_company], client, store, load_date=DAY)
    before = _files(tmp_path)
    second = run_ingest([gh_company, ashby_company], client, store, load_date=DAY)

    assert second.counts == {"unchanged": 2}
    assert _files(tmp_path) == before
    assert all(r.object_uri for r in second.rows)  # still points at the landed object


@responses.activate
def test_changed_board_lands_new_object(tmp_path, client, gh_company):
    changed = fixture_json("greenhouse_board.json")
    changed["jobs"].pop()
    responses.get(GH_URL, json=fixture_json("greenhouse_board.json"))
    responses.get(GH_URL, json=changed)
    store = LocalStorage(tmp_path)

    first = run_ingest([gh_company], client, store, load_date=DAY)
    second = run_ingest([gh_company], client, store, load_date=DAY)

    assert second.counts == {"landed": 1}
    assert second.rows[0].job_count == 1
    assert second.rows[0].content_sha256 != first.rows[0].content_sha256
    raw_files = list((tmp_path / "raw").rglob("*.json"))
    assert len(raw_files) == 2


@responses.activate
def test_board_404_is_recorded_and_other_boards_still_run(
    tmp_path, client, gh_company, ashby_company
):
    """Failure switch 1: a company changed job-board vendors."""
    responses.get(GH_URL, status=404, json={"status": 404, "error": "Job not found"})
    responses.get(ASHBY_URL, json=fixture_json("ashby_board.json"))
    store = LocalStorage(tmp_path)

    summary = run_ingest([gh_company, ashby_company], client, store, load_date=DAY)

    assert not summary.ok
    gh, ashby = summary.rows
    assert gh.status == "failed" and gh.error_type == "board_not_found" and gh.attempts == 1
    assert ashby.status == "landed"
    log_rows = [
        json.loads(line)
        for line in (tmp_path / summary.runlog_uri.split(str(tmp_path) + "/")[1])
        .read_text()
        .splitlines()
    ]
    assert log_rows[-1]["stage"] == "summary" and log_rows[-1]["status"] == "partial"


@responses.activate
def test_new_field_is_reported_not_fatal(tmp_path, client, ashby_company):
    """Failure switch 2: the vendor adds a field we have never seen."""
    payload = fixture_json("ashby_board.json")
    payload["jobs"][0]["visaSponsorship"] = "maybe"
    responses.get(ASHBY_URL, json=payload)

    summary = run_ingest([ashby_company], client, LocalStorage(tmp_path), load_date=DAY)

    assert summary.rows[0].status == "landed"
    assert summary.rows[0].new_fields == ["visaSponsorship"]


@responses.activate
@pytest.mark.parametrize(
    "body, error_type",
    [
        ({"postings": []}, "contract"),
        ({"jobs": [{"title": "no id"}]}, "contract"),
    ],
)
def test_contract_violations_fail_without_landing(tmp_path, client, gh_company, body, error_type):
    responses.get(GH_URL, json=body)
    summary = run_ingest([gh_company], client, LocalStorage(tmp_path), load_date=DAY)
    assert summary.rows[0].error_type == error_type
    assert not (tmp_path / "raw").exists()


@responses.activate
def test_invalid_json(tmp_path, client, gh_company):
    responses.get(GH_URL, body="<html>maintenance</html>", status=200)
    summary = run_ingest([gh_company], client, LocalStorage(tmp_path), load_date=DAY)
    assert summary.rows[0].error_type == "invalid_json"


@responses.activate
def test_retries_on_503_then_succeeds(tmp_path, client, gh_company):
    responses.get(GH_URL, status=503)
    responses.get(GH_URL, json=fixture_json("greenhouse_board.json"))
    summary = run_ingest([gh_company], client, LocalStorage(tmp_path), load_date=DAY)
    assert summary.rows[0].status == "landed" and summary.rows[0].attempts == 2


def test_hash_ignores_key_order_and_whitespace():
    assert canonical_sha256({"a": 1, "b": [1, 2]}) == canonical_sha256({"b": [1, 2], "a": 1})


@mock_aws
@responses.activate
def test_s3_backend_end_to_end(client, gh_company, ashby_company):
    s3 = boto3.client("s3", region_name="us-west-2")
    s3.create_bucket(
        Bucket="job-radar-test", CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
    )
    store = S3Storage("job-radar-test", prefix="dev", client=s3)
    _mock_boards()
    _mock_boards()

    first = run_ingest([gh_company, ashby_company], client, store, load_date=DAY)
    keys_after_first = {o["Key"] for o in s3.list_objects_v2(Bucket="job-radar-test")["Contents"]}
    second = run_ingest([gh_company, ashby_company], client, store, load_date=DAY)
    keys_after_second = {o["Key"] for o in s3.list_objects_v2(Bucket="job-radar-test")["Contents"]}

    assert first.counts == {"landed": 2} and second.counts == {"unchanged": 2}
    raw = sorted(k for k in keys_after_first if k.startswith("dev/raw/"))
    assert raw[0].startswith("dev/raw/ashby/examplecloud/load_date=2026-10-26/")
    # Only a second run-log file appears; raw/ and state/ are untouched.
    new_keys = keys_after_second - keys_after_first
    assert len(new_keys) == 1 and next(iter(new_keys)).startswith("dev/ops/pipeline_runs/")
    head = s3.head_object(Bucket="job-radar-test", Key=raw[0])
    assert head["Metadata"]["job-count"] == "1"
    assert head["ServerSideEncryption"] == "AES256"
