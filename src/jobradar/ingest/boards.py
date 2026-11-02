"""Job board adapters. Each one knows its URL and the minimum shape it expects.

We land the raw response untouched; validation here only checks the contract we
rely on downstream (a list of jobs, each with an id and a title) and reports any
fields we have not seen before, so schema drift shows up in the run log instead
of silently breaking the silver layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from jobradar.config import BoardSource, Company


class BoardContractError(ValueError):
    """The response parsed as JSON but broke the contract we rely on."""


class _Job(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int | str
    title: str


class _Board(BaseModel):
    model_config = ConfigDict(extra="allow")
    jobs: list[_Job]


class BoardAdapter(ABC):
    source: ClassVar[BoardSource]
    # Job-level fields we know about. Anything else is reported as a new field.
    known_job_fields: ClassVar[frozenset[str]]

    @abstractmethod
    def url(self, company: Company) -> tuple[str, dict[str, str]]:
        """Return (url, query params) for this company's board."""

    def validate(self, payload: Any) -> tuple[int, list[str]]:
        """Return (job_count, sorted new job-level fields). Raise BoardContractError."""
        try:
            board = _Board.model_validate(payload)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise BoardContractError(f"{loc}: {first['msg']}") from exc
        seen: set[str] = set()
        for job in payload["jobs"]:
            seen.update(job.keys())
        return len(board.jobs), sorted(seen - self.known_job_fields)


class GreenhouseAdapter(BoardAdapter):
    source = BoardSource.GREENHOUSE
    known_job_fields = frozenset(
        {
            "id",
            "internal_job_id",
            "title",
            "updated_at",
            "first_published",
            "requisition_id",
            "location",
            "absolute_url",
            "metadata",
            "data_compliance",
            "content",
            "departments",
            "offices",
            "company_name",
            "language",
        }
    )

    def url(self, company: Company) -> tuple[str, dict[str, str]]:
        return (
            f"https://boards-api.greenhouse.io/v1/boards/{company.board_token}/jobs",
            {"content": "true"},
        )


class AshbyAdapter(BoardAdapter):
    source = BoardSource.ASHBY
    known_job_fields = frozenset(
        {
            "id",
            "title",
            "department",
            "team",
            "employmentType",
            "location",
            "secondaryLocations",
            "publishedAt",
            "updatedAt",
            "isListed",
            "isRemote",
            "workplaceType",
            "address",
            "jobUrl",
            "applyUrl",
            "descriptionHtml",
            "descriptionPlain",
            "compensation",
            "shouldDisplayCompensationOnJobPostings",
        }
    )

    def url(self, company: Company) -> tuple[str, dict[str, str]]:
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{company.board_token}",
            {"includeCompensation": "true"},
        )


ADAPTERS: dict[BoardSource, BoardAdapter] = {
    BoardSource.GREENHOUSE: GreenhouseAdapter(),
    BoardSource.ASHBY: AshbyAdapter(),
}
