import json
from pathlib import Path

import pytest
import responses

from jobradar.ops.databricks import DatabricksError, DatabricksJobs

HOST = "dbc-test.cloud.databricks.com"
API = f"https://{HOST}/api/2.1/jobs"
SPEC = json.loads(
    (Path(__file__).resolve().parents[1] / "infra/databricks/daily_job.json").read_text()
)


def _client():
    return DatabricksJobs(HOST, "token")


def test_job_spec_runs_the_notebooks_in_order():
    tasks = {t["task_key"]: t for t in SPEC["tasks"]}
    assert tasks["silver_postings"]["depends_on"] == [{"task_key": "bronze_job_boards"}]
    assert {d["task_key"] for d in tasks["silver_employer_matches"]["depends_on"]} == {
        "silver_postings",
        "silver_lca_filings",
    }
    for t in SPEC["tasks"]:
        path = Path(__file__).resolve().parents[1] / f"{t['notebook_task']['notebook_path']}.py"
        assert path.exists(), f"{path} is missing"


@responses.activate
def test_deploy_creates_then_updates():
    responses.get(f"{API}/list", json={})
    responses.post(f"{API}/create", json={"job_id": 42})
    assert _client().deploy(SPEC) == (42, "created")

    responses.replace(
        responses.GET, f"{API}/list", json={"jobs": [{"job_id": 42, "settings": SPEC}]}
    )
    responses.post(f"{API}/reset", json={})
    assert _client().deploy(SPEC) == (42, "updated")
    assert json.loads(responses.calls[-1].request.body)["job_id"] == 42


@responses.activate
def test_run_and_wait_until_terminated():
    responses.post(f"{API}/run-now", json={"run_id": 7})
    responses.get(f"{API}/runs/get", json={"state": {"life_cycle_state": "RUNNING"}})
    responses.get(
        f"{API}/runs/get",
        json={
            "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
            "run_page_url": "https://x/run/7",
        },
    )
    client = _client()
    run_id = client.run_now(42, {"env": "prod"})
    assert json.loads(responses.calls[0].request.body)["job_parameters"] == {"env": "prod"}

    result = client.wait(run_id, poll_s=1, sleep=lambda _: None)
    assert result.ok and result.run_page_url == "https://x/run/7"


@responses.activate
def test_errors_are_reported_with_status():
    responses.get(f"{API}/list", status=403, body="Invalid access token")
    with pytest.raises(DatabricksError, match="HTTP 403"):
        _client().find_job("job-radar-daily")
