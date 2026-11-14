"""Where the assistant's model runs: the Claude API (Anthropic) or Amazon Bedrock.

Both clients expose the same messages.create(...) interface, so the assistant loop does
not change; only the client and the model id do. That makes the provider a setting, which
is the fallback plan if one provider has an outage.

    anthropic: ANTHROPIC_API_KEY; model JOBRADAR_AGENT_MODEL (default in assistant.py)
    bedrock:   AWS credentials from a profile (JOBRADAR_BEDROCK_PROFILE, default
               jobradar-admin) in JOBRADAR_BEDROCK_REGION (default us-west-2);
               model JOBRADAR_BEDROCK_MODEL, a Bedrock inference profile id such as
               us.anthropic.claude-...
"""

from __future__ import annotations

import os

PROVIDERS = ("anthropic", "bedrock")


def make_client(provider: str):
    """An Anthropic-compatible client for the chosen provider."""
    import anthropic

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY in .env (never paste it in chat or commit it)")
        return anthropic.Anthropic()
    if provider == "bedrock":
        return anthropic.AnthropicBedrock(
            aws_profile=os.environ.get("JOBRADAR_BEDROCK_PROFILE", "jobradar-admin"),
            aws_region=os.environ.get("JOBRADAR_BEDROCK_REGION", "us-west-2"),
        )
    raise SystemExit(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")


def default_model(provider: str, fallback: str) -> str:
    if provider == "bedrock":
        model = os.environ.get("JOBRADAR_BEDROCK_MODEL")
        if not model:
            raise SystemExit(
                "Set JOBRADAR_BEDROCK_MODEL in .env to a Bedrock inference profile id, "
                "e.g. from: aws bedrock list-inference-profiles"
            )
        return model
    return fallback
