"""Providers (Claude API vs Bedrock) and the comparison report."""

import json

import pytest

from jobradar.agent.providers import default_model, make_client
from jobradar.evals.compare import compare_runs


def test_bedrock_client_uses_the_profile_and_region(monkeypatch):
    monkeypatch.setenv("JOBRADAR_BEDROCK_PROFILE", "some-profile")
    monkeypatch.setenv("JOBRADAR_BEDROCK_REGION", "us-west-2")
    import anthropic

    seen = {}
    monkeypatch.setattr(anthropic, "AnthropicBedrock", lambda **kw: seen.update(kw) or "client")
    assert make_client("bedrock") == "client"
    assert seen == {"aws_profile": "some-profile", "aws_region": "us-west-2"}


def test_anthropic_needs_a_key_and_bedrock_needs_a_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        make_client("anthropic")
    monkeypatch.delenv("JOBRADAR_BEDROCK_MODEL", raising=False)
    with pytest.raises(SystemExit, match="JOBRADAR_BEDROCK_MODEL"):
        default_model("bedrock", "x")
    monkeypatch.setenv("JOBRADAR_BEDROCK_MODEL", "us.anthropic.claude-test")
    assert default_model("bedrock", "x") == "us.anthropic.claude-test"
    assert default_model("anthropic", "claude-sonnet-5-5") == "claude-sonnet-5-5"
    with pytest.raises(SystemExit, match="unknown provider"):
        make_client("openai")


def _run(path, model, rows):
    base = {"reasons": [], "input_tokens": 1000, "output_tokens": 100, "model": model}
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows) + "\n")
    return path


def test_compare_shows_accuracy_speed_cost_and_differences(tmp_path):
    q = {"category": "Counts", "question": "How many?"}
    a = _run(tmp_path / "a.jsonl", "anthropic:sonnet", [
        {**q, "id": "C01", "passed": True, "seconds": 10.0},
        {**q, "id": "C02", "passed": True, "seconds": 20.0},
        {"id": "X01", "category": "Safety", "question": "Delete", "passed": True, "seconds": 4.0},
    ])  # fmt: skip
    b = _run(tmp_path / "b.jsonl", "bedrock:us.anthropic.sonnet", [
        {**q, "id": "C01", "passed": True, "seconds": 12.0},
        {**q, "id": "C02", "passed": False, "seconds": 30.0, "reasons": ["number: expected 7"]},
    ])  # fmt: skip
    text = compare_runs(a, b)
    assert "anthropic:sonnet vs bedrock:us.anthropic.sonnet" in text
    assert "Same 2 questions" in text  # X01 only in one run: left out
    assert "| Passed | 2 of 2 | 1 of 2 |" in text
    assert "| Median seconds per question | 15.0 | 21.0 |" in text
    assert "**C02** How many?: passed on anthropic:sonnet only (number: expected 7)" in text


def test_cost_uses_each_models_price():
    from jobradar.evals.runner import cost_usd

    assert round(cost_usd("anthropic:claude-sonnet-5-5", 1_000_000, 100_000), 2) == 3.0
    assert round(cost_usd("anthropic:claude-haiku-5-5", 1_000_000, 100_000), 2) == 0.15
