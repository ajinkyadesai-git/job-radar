"""The deploy workflow: keyless, main only, health-checked, with rollback."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"
TEXT = WORKFLOW.read_text()
FLOW = yaml.safe_load(TEXT)
STEPS = FLOW["jobs"]["deploy"]["steps"]


def _step(name_part):
    return next(s for s in STEPS if name_part in s.get("name", ""))


def test_runs_on_merge_to_main_only_and_never_in_parallel():
    on = FLOW[True]  # YAML reads the key "on" as True
    assert on["push"]["branches"] == ["main"] and "pull_request" not in on
    assert FLOW["concurrency"]["cancel-in-progress"] is False


def test_uses_oidc_not_stored_aws_keys():
    assert FLOW["permissions"] == {"id-token": "write", "contents": "read"}
    for word in ("aws-access-key-id", "AWS_SECRET_ACCESS_KEY", "aws-secret-access-key"):
        assert word not in TEXT
    assert "secrets.AWS_DEPLOY_ROLE_ARN" in _step("Sign in to AWS")["with"]["role-to-assume"]


def test_images_are_tagged_by_commit_and_built_for_arm():
    assert FLOW["jobs"]["deploy"]["runs-on"].endswith("-arm")
    assert "GITHUB_SHA::12" in _step("Sign in to ECR")["run"]
    assert "--provenance=false" in _step("Build and push")["run"]


def test_health_check_then_rollback_on_failure():
    names = [s.get("name", "") for s in STEPS]
    assert names.index("Remember the running image (for rollback)") < names.index("Update Lambda")
    assert names.index("Update Lambda") < names.index("Check /health")
    rollback = _step("Roll back")
    assert rollback["if"] == "failure() && steps.health.outcome == 'failure'"
    assert "$PREVIOUS" in rollback["run"] and "exit 1" in rollback["run"]


def test_watchdog_follows_the_api_image_only_after_a_healthy_deploy():
    names = [s.get("name", "") for s in STEPS]
    assert names.index("Check /health") < names.index("Update the watchdog to the same image")
    assert "job-radar-watchdog" in _step("Update the watchdog")["run"]


def test_actions_run_on_node_24_versions():
    workflows = WORKFLOW.parent.glob("*.yml")
    for path in workflows:
        text = path.read_text()
        for old in (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "credentials@v4",
            "credentials@v5",
        ):
            assert old not in text, f"{path.name} still uses {old}"


def test_eval_smoke_runs_on_agent_changes_and_fails_the_check():
    smoke = yaml.safe_load((WORKFLOW.parent / "evals-smoke.yml").read_text())
    paths = smoke[True]["pull_request"]["paths"]
    assert "src/jobradar/agent/**" in paths and "evals/questions.csv" in paths
    env = smoke["jobs"]["safety"]["env"]
    assert env["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY_CI }}"
    run = next(s["run"] for s in smoke["jobs"]["safety"]["steps"] if "Ask" in s.get("name", ""))
    assert "--strict" in run and "X01" in run


def test_no_workflow_uses_stored_aws_keys():
    for path in WORKFLOW.parent.glob("*.yml"):
        text = path.read_text()
        assert "AWS_ACCESS_KEY_ID" not in text and "AWS_SECRET_ACCESS_KEY" not in text, path.name
    daily = yaml.safe_load((WORKFLOW.parent / "daily.yml").read_text())
    assert daily["permissions"]["id-token"] == "write"
    steps = daily["jobs"]["daily"]["steps"]
    sign_in = next(i for i, s in enumerate(steps) if "Sign in to AWS" in s.get("name", ""))
    ingest = next(i for i, s in enumerate(steps) if "Ingest" in s.get("name", ""))
    assert sign_in < ingest
