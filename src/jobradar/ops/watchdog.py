"""The daily watchdog: did today's pipeline run, and is the data fresh? Email if not.

Runs on AWS Lambda once a day (EventBridge schedule), a few hours after the GitHub daily run
is due. It catches the failures GitHub's own email does not: a scheduled run GitHub skipped,
and gold data that stopped updating. Problems go to an SNS topic, which emails you.

    1. Ingest ran today: a run log exists under <prefix>/ops/pipeline_runs/run_date=<today>/
       and its summary row is not "failed_all".
    2. Gold is fresh: max(last_seen) in fct_postings is today.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from jobradar.agent.sql_guard import check


@dataclass
class Report:
    day: str
    problems: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_ingest(s3, bucket: str, prefix: str, day: date, report: Report) -> None:
    key_prefix = f"{prefix}/ops/pipeline_runs/run_date={day.isoformat()}/"
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=key_prefix)
    objects = sorted(resp.get("Contents", []), key=lambda o: o["LastModified"])
    report.checks["ingest_runs_today"] = len(objects)
    if not objects:
        report.problems.append(
            f"No ingest run today ({day}): GitHub may have skipped the daily schedule. "
            "Start it with: gh workflow run daily"
        )
        return
    body = s3.get_object(Bucket=bucket, Key=objects[-1]["Key"])["Body"].read().decode()
    rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    summary = next((r for r in reversed(rows) if r.get("stage") == "summary"), None)
    status = summary.get("status") if summary else None
    report.checks["ingest_status"] = status
    if status == "failed_all":
        report.problems.append(f"Today's ingest failed on every board ({day}).")


def check_freshness(runner, env: str, day: date, report: Report) -> None:
    _, rows = runner.run(check("select max(last_seen) as last_seen from fct_postings", env=env).sql)
    last = rows[0][0] if rows else None
    if isinstance(last, datetime):
        last = last.date()
    report.checks["gold_last_seen"] = str(last)
    if last is None or last < day:
        report.problems.append(
            f"Gold data is stale: newest last_seen is {last}, expected {day}. "
            "The Databricks job or dbt build probably failed; check the daily run on GitHub."
        )


def run_watchdog(
    s3,
    runner,
    sns=None,
    topic_arn: str | None = None,
    bucket: str = "",
    prefix: str = "prod",
    env: str = "prod",
    today: date | None = None,
) -> Report:
    day = today or datetime.now(UTC).date()
    report = Report(day=day.isoformat())
    for name, fn in (
        ("ingest", lambda: check_ingest(s3, bucket, prefix, day, report)),
        ("freshness", lambda: check_freshness(runner, env, day, report)),
    ):
        try:
            fn()
        except Exception as e:  # a check that cannot run is itself a problem worth an email
            report.problems.append(f"Could not check {name}: {str(e).splitlines()[0][:200]}")
    if report.problems and sns is not None and topic_arn:
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"Job Radar: {len(report.problems)} problem(s) on {day}",
            Message="\n\n".join(report.problems)
            + f"\n\nChecks: {json.dumps(report.checks, default=str)}",
        )
    return report


def run_from_environment() -> Report:
    """Wiring for Lambda: AWS clients, the Databricks runner and settings from env vars."""
    import boto3

    from jobradar.agent.tools import DatabricksRunner

    env = os.environ.get("JOBRADAR_API_ENV", "prod")
    runner = DatabricksRunner(env=env)
    try:
        return run_watchdog(
            s3=boto3.client("s3"),
            runner=runner,
            sns=boto3.client("sns"),
            topic_arn=os.environ.get("JOBRADAR_ALERT_TOPIC_ARN"),
            bucket=os.environ["JOBRADAR_S3_BUCKET"],
            prefix=os.environ.get("JOBRADAR_S3_PREFIX", "prod"),
            env=env,
        )
    finally:
        runner.close()
