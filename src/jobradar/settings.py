"""Runtime settings, read from environment variables (and a local .env file).

Secrets never live in code or config files that get committed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBRADAR_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "prod"] = "dev"
    # Where raw responses land. "local" mirrors the S3 layout under ./data for offline dev.
    dest: Literal["s3", "local"] = "local"
    s3_bucket: str | None = None
    # Optional prefix so dev and prod can share one bucket: s3://bucket/<prefix>/raw/...
    s3_prefix: str = ""
    local_root: str = "data"
    aws_region: str = "us-west-2"

    companies_file: str = "config/companies.yaml"
    requests_per_second: float = Field(default=1.0, gt=0, le=5)
    http_timeout_s: float = 30.0
    max_retries: int = 3
    user_agent: str = "job-radar/0.1 (+https://github.com/ajinkyadesai-git/job-radar)"


def get_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]
