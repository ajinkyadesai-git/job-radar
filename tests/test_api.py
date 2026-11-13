"""The API: health, key checks, safe query building, search and ask with fakes."""

from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from jobradar.api.app import Services, app, get_services

KEY = {"X-API-Key": "test-key"}


class Runner:
    def __init__(self):
        self.ran = []

    def run(self, sql):
        self.ran.append(sql)
        return ["company_name", "title", "fit_score"], [("Ramp", "Technical Consultant", 0.86)]

    def describe(self):
        return "(schema)"


class Searcher:
    def search(self, query, k=6, my_level_only=True):
        self.last = (query, k, my_level_only)
        return [NS(posting_key="ashby:1", company="Ramp", title="Technical Consultant",
                   url="https://x/1", location="NYC", years_required=2.0, fit_score=0.86,
                   score=0.71234567, passage="NetSuite and Python integrations")]  # fmt: skip


def _resp(content, stop):
    return NS(content=content, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


class Client:
    def __init__(self):
        self.messages = self
        self.sent = []
        sql = {"sql": "select count(*) from fct_postings"}
        self.responses = [
            _resp([NS(type="tool_use", id="t1", name="run_sql", input=sql)], "tool_use"),
            _resp([NS(type="text", text="About 15,000 open jobs.")], "end_turn"),
        ]

    def create(self, **kw):
        self.sent.append(kw)
        return self.responses.pop(0)


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("JOBRADAR_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    s = Services(env="prod", _runner=Runner(), _searcher=Searcher(), _client=Client())
    app.dependency_overrides[get_services] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def api(svc):
    return TestClient(app)


def test_health_needs_no_key_and_touches_nothing(api, svc):
    r = api.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert svc._runner.ran == []


def test_key_is_required_and_checked(api):
    assert api.get("/jobs/today").status_code == 401
    assert api.get("/jobs/today", headers={"X-API-Key": "wrong"}).status_code == 401
    assert api.get("/jobs/today", headers=KEY).status_code == 200


def test_endpoints_are_disabled_when_no_key_is_configured(api, monkeypatch):
    monkeypatch.delenv("JOBRADAR_API_KEY")
    r = api.get("/jobs/today", headers=KEY)
    assert r.status_code == 503 and "JOBRADAR_API_KEY" in r.json()["detail"]


def test_today_builds_a_guarded_query_from_allowed_values_only(api, svc):
    r = api.get("/jobs/today?limit=5&reach=Stretch&role_family=Software", headers=KEY)
    assert r.status_code == 200
    assert r.json() == {"count": 1, "jobs": [
        {"company_name": "Ramp", "title": "Technical Consultant", "fit_score": 0.86}]}  # fmt: skip
    sql = svc._runner.ran[-1]
    assert "workspace.jobradar_gold.mart_new_postings" in sql  # went through the SQL guard
    assert "reach = 'Stretch'" in sql and "role_family = 'Software'" in sql
    assert "LIMIT 5" in sql.upper()


@pytest.mark.parametrize(
    "query",
    [
        "limit=0", "limit=101", "reach=Senior", "role_family=Sales",
        "role_family=Software' or '1'='1",
    ],
)  # fmt: skip
def test_today_rejects_values_outside_the_allowed_lists(api, svc, query):
    assert api.get(f"/jobs/today?{query}", headers=KEY).status_code == 422
    assert svc._runner.ran == []


def test_search_returns_passages_and_validates_input(api, svc):
    r = api.get("/jobs/search?q=NetSuite%20Python&k=3&my_level_only=false", headers=KEY)
    body = r.json()
    assert r.status_code == 200 and body["results"][0]["match"] == 0.7123
    assert svc._searcher.last == ("NetSuite Python", 3, False)
    assert api.get("/jobs/search?q=x", headers=KEY).status_code == 422
    assert api.get("/jobs/search?q=dbt&k=50", headers=KEY).status_code == 422


def test_search_without_an_index_is_a_clear_503(api, svc):
    svc._searcher, svc.searcher_checked = None, True
    r = api.get("/jobs/search?q=dbt", headers=KEY)
    assert r.status_code == 503 and "index" in r.json()["detail"]


def test_ask_runs_the_assistant_without_the_resume_tool(api, svc):
    r = api.post("/ask", json={"question": "How many jobs are open?"}, headers=KEY)
    body = r.json()
    assert r.status_code == 200 and body["answer"] == "About 15,000 open jobs."
    assert body["tools"] == ["run_sql"] and body["queries"][0]["ok"] is True
    offered = [t["name"] for t in svc._client.sent[0]["tools"]]
    assert "resume_fit" not in offered and "run_sql" in offered


def test_ask_validates_the_question(api):
    assert api.post("/ask", json={"question": "hi"}, headers=KEY).status_code == 422
    assert api.post("/ask", json={"question": "x" * 501}, headers=KEY).status_code == 422
    assert api.post("/ask", json={}, headers=KEY).status_code == 422


def test_secrets_load_from_ssm_without_overriding_the_environment(monkeypatch):
    import boto3
    from moto import mock_aws

    from jobradar.api.app import load_secrets_from_ssm

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "set-locally")
    monkeypatch.delenv("JOBRADAR_TEST_TOKEN", raising=False)
    with mock_aws():
        ssm = boto3.client("ssm")
        for name, value in [("JOBRADAR_TEST_TOKEN", "from-ssm"), ("DATABRICKS_HTTP_PATH", "x")]:
            ssm.put_parameter(Name=f"/job-radar/prod/{name}", Value=value, Type="SecureString")
        ssm.put_parameter(Name="/job-radar/dev/OTHER", Value="no", Type="SecureString")
        loaded = load_secrets_from_ssm("/job-radar/prod/")
    assert loaded == ["JOBRADAR_TEST_TOKEN"]
    import os

    assert os.environ["JOBRADAR_TEST_TOKEN"] == "from-ssm"
    assert os.environ["DATABRICKS_HTTP_PATH"] == "set-locally"  # environment wins
    assert "OTHER" not in os.environ
    monkeypatch.delenv("JOBRADAR_TEST_TOKEN")


def test_no_prefix_means_no_ssm_call(monkeypatch):
    from jobradar.api.app import load_secrets_from_ssm

    monkeypatch.delenv("JOBRADAR_SSM_PREFIX", raising=False)
    assert load_secrets_from_ssm() == []
