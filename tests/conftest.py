from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobradar.config import BoardSource, Company
from jobradar.ingest.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"

GH_URL = "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/examplecloud"


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def gh_company() -> Company:
    return Company(
        slug="examplecorp",
        name="ExampleCorp",
        source=BoardSource.GREENHOUSE,
        board_token="examplecorp",
    )


@pytest.fixture
def ashby_company() -> Company:
    return Company(
        slug="examplecloud",
        name="ExampleCloud",
        source=BoardSource.ASHBY,
        board_token="examplecloud",
    )


@pytest.fixture
def client() -> PoliteClient:
    # Real rate limiter logic, but no actual sleeping in tests.
    return PoliteClient(requests_per_second=1000, max_retries=2, sleep=lambda s: None)
