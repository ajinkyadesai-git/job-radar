"""Company list: which job boards to pull, validated with pydantic."""

from __future__ import annotations

import csv
import io
import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BoardSource(StrEnum):
    GREENHOUSE = "greenhouse"
    ASHBY = "ashby"


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="Our stable id for the company, used in S3 paths.")
    name: str
    source: BoardSource
    board_token: str = Field(description="The company's token on the job board vendor.")
    tier: str = Field(default="B", pattern="^[AB]$")
    enabled: bool = True

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError(f"slug must be lowercase letters, digits, '-' or '_': {v!r}")
        return v


class CompanyList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companies: list[Company]

    @model_validator(mode="after")
    def _unique(self) -> CompanyList:
        seen: set[str] = set()
        for c in self.companies:
            if c.slug in seen:
                raise ValueError(f"duplicate company slug: {c.slug}")
            seen.add(c.slug)
        return self

    def enabled(self, only: list[str] | None = None) -> list[Company]:
        rows = [c for c in self.companies if c.enabled]
        if only:
            wanted = set(only)
            unknown = wanted - {c.slug for c in self.companies}
            if unknown:
                raise ValueError(f"unknown company slug(s): {sorted(unknown)}")
            rows = [c for c in rows if c.slug in wanted]
        return rows


def load_companies(path: str | Path) -> CompanyList:
    data = yaml.safe_load(Path(path).read_text())
    return CompanyList.model_validate(data)


SEED_COLUMNS = ("slug", "name", "source", "board_token", "tier", "enabled")


def companies_seed_csv(companies: CompanyList) -> str:
    """The company list as the CSV dbt loads as a seed (dbt/seeds/companies.csv)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(SEED_COLUMNS)
    for c in companies.companies:
        writer.writerow(
            [c.slug, c.name, c.source.value, c.board_token, c.tier, str(c.enabled).lower()]
        )
    return buf.getvalue()
