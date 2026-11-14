"""The daily watchdog: missing run, failed run, stale data, and the email it sends."""

import io
import json
from datetime import date, datetime

import boto3
import pytest
from moto import mock_aws

from jobradar.ops.watchdog import run_watchdog

DAY = date(2026, 11, 13)
BUCKET = "jr-test"


class Runner:
    def __init__(self, last_seen=DAY, fail=False):
        self.last_seen, self.fail, self.ran = last_seen, fail, []

    def run(self, sql):
        self.ran.append(sql)
        if self.fail:
            raise RuntimeError("warehouse unreachable\nstack")
        return ["last_seen"], [(self.last_seen,)]


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        s3, sns = boto3.client("s3"), boto3.client("sns")
        s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
        )
        topic = sns.create_topic(Name="alerts")["TopicArn"]
        sqs = boto3.client("sqs")
        queue = sqs.create_queue(QueueName="inbox")["QueueUrl"]
        qarn = sqs.get_queue_attributes(QueueUrl=queue, AttributeNames=["QueueArn"])
        sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=qarn["Attributes"]["QueueArn"])
        yield s3, sns, topic, sqs, queue


def _runlog(s3, status="success", day=DAY):
    rows = [{"stage": "fetch_board", "status": "ok"}, {"stage": "summary", "status": status}]
    body = "\n".join(json.dumps(r) for r in rows)
    key = f"prod/ops/pipeline_runs/run_date={day.isoformat()}/run_id=abc.jsonl"
    s3.upload_fileobj(io.BytesIO(body.encode()), BUCKET, key)


def _inbox(sqs, queue):
    msgs = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=10).get("Messages", [])
    return [json.loads(m["Body"]) for m in msgs]


def test_all_good_sends_nothing(aws):
    s3, sns, topic, sqs, queue = aws
    _runlog(s3)
    r = run_watchdog(s3, Runner(), sns, topic, bucket=BUCKET, today=DAY)
    assert r.ok and r.checks == {"ingest_runs_today": 1, "ingest_status": "success",
                                 "gold_last_seen": "2026-11-13"}  # fmt: skip
    assert _inbox(sqs, queue) == []


def test_skipped_run_and_stale_gold_send_one_email(aws):
    s3, sns, topic, sqs, queue = aws
    r = run_watchdog(s3, Runner(last_seen=date(2026, 11, 12)), sns, topic, bucket=BUCKET,
                     today=DAY)  # fmt: skip
    assert len(r.problems) == 2
    assert "skipped" in r.problems[0] and "gh workflow run daily" in r.problems[0]
    assert "stale" in r.problems[1]
    mail = _inbox(sqs, queue)
    assert len(mail) == 1 and mail[0]["Subject"] == "Job Radar: 2 problem(s) on 2026-11-13"


def test_run_that_failed_on_every_board_is_reported(aws):
    s3, sns, topic, *_ = aws
    _runlog(s3, status="failed_all")
    r = run_watchdog(s3, Runner(last_seen=datetime(2026, 11, 13, 15, 0)), sns, topic,
                     bucket=BUCKET, today=DAY)  # fmt: skip
    assert r.problems == ["Today's ingest failed on every board (2026-11-13)."]


def test_a_check_that_cannot_run_is_itself_reported(aws):
    s3, sns, topic, *_ = aws
    _runlog(s3)
    r = run_watchdog(s3, Runner(fail=True), sns, topic, bucket=BUCKET, today=DAY)
    assert r.problems == ["Could not check freshness: warehouse unreachable"]


def test_freshness_query_goes_through_the_sql_guard(aws):
    s3, *_ = aws
    _runlog(s3)
    runner = Runner()
    run_watchdog(s3, runner, bucket=BUCKET, today=DAY)
    assert "workspace.jobradar_gold.fct_postings" in runner.ran[0]


def test_events_route_exists_only_on_the_watchdog(monkeypatch):
    import importlib

    import jobradar.api.app as appmod

    monkeypatch.delenv("JOBRADAR_WATCHDOG", raising=False)
    public = importlib.reload(appmod)
    assert "/events" not in [r.path for r in public.app.routes]
    monkeypatch.setenv("JOBRADAR_WATCHDOG", "1")
    watchdog = importlib.reload(appmod)
    assert "/events" in [r.path for r in watchdog.app.routes]
    monkeypatch.delenv("JOBRADAR_WATCHDOG")
    importlib.reload(appmod)
