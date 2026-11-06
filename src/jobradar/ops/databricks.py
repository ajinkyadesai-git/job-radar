"""Deploy and run the daily Databricks job through the Jobs REST API.

The job is defined as code in ``infra/databricks/daily_job.json``. ``deploy`` creates it, or
replaces its settings if a job with the same name exists, so deploying twice is safe.
``run_now`` starts a run and ``wait`` polls until it finishes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

TERMINAL_STATES = frozenset({"TERMINATED", "SKIPPED", "INTERNAL_ERROR"})


class DatabricksError(RuntimeError):
    pass


@dataclass
class RunResult:
    run_id: int
    life_cycle_state: str
    result_state: str | None
    state_message: str
    run_page_url: str | None

    @property
    def ok(self) -> bool:
        return self.result_state == "SUCCESS"


class DatabricksJobs:
    def __init__(
        self,
        host: str,
        token: str,
        session: requests.Session | None = None,
        timeout_s: float = 30,
    ) -> None:
        host = host.strip().rstrip("/")
        self.base = host if host.startswith("https://") else f"https://{host}"
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.timeout_s = timeout_s

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = self.session.request(
            method, f"{self.base}/api/2.1/jobs/{path}", timeout=self.timeout_s, **kw
        )
        if resp.status_code >= 400:
            raise DatabricksError(f"{method} {path}: HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def find_job(self, name: str) -> int | None:
        jobs = self._call("GET", "list", params={"name": name}).get("jobs") or []
        matches = [j["job_id"] for j in jobs if j.get("settings", {}).get("name") == name]
        if len(matches) > 1:
            raise DatabricksError(f"{len(matches)} jobs are named {name!r}; delete the extras")
        return matches[0] if matches else None

    def deploy(self, settings: dict[str, Any]) -> tuple[int, str]:
        """Create the job, or reset an existing job with the same name. Returns (id, action)."""
        job_id = self.find_job(settings["name"])
        if job_id is None:
            return self._call("POST", "create", json=settings)["job_id"], "created"
        self._call("POST", "reset", json={"job_id": job_id, "new_settings": settings})
        return job_id, "updated"

    def run_now(self, job_id: int, params: dict[str, str] | None = None) -> int:
        body: dict[str, Any] = {"job_id": job_id}
        if params:
            body["job_parameters"] = params
        return self._call("POST", "run-now", json=body)["run_id"]

    def get_run(self, run_id: int) -> RunResult:
        run = self._call("GET", "runs/get", params={"run_id": run_id})
        state = run.get("state", {})
        return RunResult(
            run_id=run_id,
            life_cycle_state=state.get("life_cycle_state", "UNKNOWN"),
            result_state=state.get("result_state"),
            state_message=state.get("state_message", ""),
            run_page_url=run.get("run_page_url"),
        )

    def wait(
        self,
        run_id: int,
        timeout_s: float = 3600,
        poll_s: float = 20,
        sleep: Callable[[float], None] = time.sleep,
    ) -> RunResult:
        waited = 0.0
        while True:
            result = self.get_run(run_id)
            if result.life_cycle_state in TERMINAL_STATES:
                return result
            if waited >= timeout_s:
                raise DatabricksError(
                    f"run {run_id} still {result.life_cycle_state} after {timeout_s}s"
                )
            sleep(poll_s)
            waited += poll_s
