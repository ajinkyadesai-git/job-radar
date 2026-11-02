from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from jobradar.config import CompanyList, load_companies
from jobradar.ingest.http import RateLimiter

REPO = Path(__file__).resolve().parents[1]


def test_repo_companies_yaml_is_valid():
    companies = load_companies(REPO / "config" / "companies.yaml")
    enabled = companies.enabled()
    assert 20 <= len(enabled) <= 30
    assert any(c.slug == "crusoe" and c.source == "ashby" for c in enabled)


def test_duplicate_slugs_rejected():
    row = {"slug": "a", "name": "A", "source": "ashby", "board_token": "a"}
    with pytest.raises(ValidationError, match="duplicate"):
        CompanyList.model_validate({"companies": [row, row]})


def test_unknown_source_and_bad_slug_rejected():
    with pytest.raises(ValidationError):
        CompanyList.model_validate(
            {"companies": [{"slug": "a", "name": "A", "source": "lever", "board_token": "a"}]}
        )
    with pytest.raises(ValidationError):
        CompanyList.model_validate(
            {
                "companies": [
                    {"slug": "Bad Slug", "name": "A", "source": "ashby", "board_token": "a"}
                ]
            }
        )


def test_only_filter_rejects_unknown_slug():
    companies = load_companies(REPO / "config" / "companies.yaml")
    with pytest.raises(ValueError, match="unknown"):
        companies.enabled(["not-a-company"])


def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        t[0] += s

    limiter = RateLimiter(1.0, clock=lambda: t[0], sleep=sleep)
    limiter.wait()  # first call: no wait
    t[0] += 0.25
    limiter.wait()  # 0.25s later: must wait 0.75s
    limiter.wait()  # immediately again: must wait a full second
    assert slept == pytest.approx([0.75, 1.0])
