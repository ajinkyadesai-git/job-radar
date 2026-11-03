"""Turn one raw job board response into one record per posting.

Used by the silver Spark job (as a UDF) and by tests. Standard library only, so the
module can be shipped to Spark workers as-is.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

# Order and names of the fields every parser returns; the Spark schema follows this list.
POSTING_FIELDS: tuple[str, ...] = (
    "posting_id",
    "title",
    "department",
    "team",
    "location",
    "is_remote",
    "workplace_type",
    "employment_type",
    "url",
    "published_at",
    "source_updated_at",
    "description_text",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_interval",
    "salary_source",
)

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</(p|div|li|h[1-6]|ul|ol|tr)>|<br\s*/?>", re.IGNORECASE)
_SPACES_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")

# "$150,000 - $200,000", "$150,000—$200,000 USD", "$150,000 to $200,000"
_SALARY_RE = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])"
    r"(?:\.\d{2})?\s*(?:-|–|—|to)\s*"
    r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])"
)


def html_to_text(value: str | None) -> str | None:
    """HTML (possibly escaped once, as Greenhouse sends it) to plain text with paragraph breaks."""
    if not value:
        return None
    text = html.unescape(value)
    if "&lt;" in text or "&amp;" in text:  # escaped twice
        text = html.unescape(text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)  # entities that were inside tags, such as &nbsp;
    text = text.replace("\xa0", " ")
    text = _SPACES_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()
    return text or None


def _money(token: str) -> float:
    token = token.replace(",", "").replace(" ", "")
    if token[-1] in "kK":
        return float(token[:-1]) * 1000
    return float(token)


def salary_from_text(text: str | None) -> tuple[float, float] | None:
    """First USD annual-looking range in a description, as (min, max); None if not found."""
    if not text:
        return None
    for m in _SALARY_RE.finditer(text):
        low, high = _money(m.group(1)), _money(m.group(2))
        # Keep plausible annual salaries only; hourly or monthly figures are left out.
        if 20_000 <= low <= high <= 2_000_000:
            return low, high
    return None


def _empty() -> dict[str, Any]:
    return dict.fromkeys(POSTING_FIELDS)


def _with_text_salary(row: dict[str, Any]) -> dict[str, Any]:
    if row["salary_min"] is None:
        found = salary_from_text(row["description_text"])
        if found:
            row["salary_min"], row["salary_max"] = found
            row["salary_currency"], row["salary_interval"] = "USD", "YEAR"
            row["salary_source"] = "description"
    return row


def parse_greenhouse(board: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for job in board.get("jobs") or []:
        row = _empty()
        location = (job.get("location") or {}).get("name")
        departments = job.get("departments") or []
        row.update(
            posting_id=str(job["id"]),
            title=job.get("title"),
            department=departments[0].get("name") if departments else None,
            location=location,
            is_remote=("remote" in location.lower()) if location else None,
            url=job.get("absolute_url"),
            published_at=job.get("first_published"),
            source_updated_at=job.get("updated_at"),
            description_text=html_to_text(job.get("content")),
        )
        rows.append(_with_text_salary(row))
    return rows


def parse_ashby(board: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for job in board.get("jobs") or []:
        row = _empty()
        description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml"))
        row.update(
            posting_id=str(job["id"]),
            title=job.get("title"),
            department=job.get("department"),
            team=job.get("team"),
            location=job.get("location"),
            is_remote=job.get("isRemote"),
            workplace_type=job.get("workplaceType"),
            employment_type=job.get("employmentType"),
            url=job.get("jobUrl"),
            published_at=job.get("publishedAt"),
            source_updated_at=job.get("updatedAt"),
            description_text=description.strip() if description else None,
        )
        for comp in (job.get("compensation") or {}).get("summaryComponents") or []:
            if comp.get("compensationType") == "Salary" and comp.get("minValue") is not None:
                interval = (comp.get("interval") or "").upper()
                row.update(
                    salary_min=float(comp["minValue"]),
                    salary_max=float(comp.get("maxValue") or comp["minValue"]),
                    salary_currency=comp.get("currencyCode"),
                    salary_interval="YEAR" if "YEAR" in interval else interval or None,
                    salary_source="structured",
                )
                break
        rows.append(_with_text_salary(row))
    return rows


PARSERS = {"greenhouse": parse_greenhouse, "ashby": parse_ashby}


def parse_board(source: str, raw_json: str) -> list[dict[str, Any]]:
    """All postings in one raw board response. Raises on an unknown source or bad JSON."""
    return PARSERS[source](json.loads(raw_json))


def parse_board_rows(source: str, raw_json: str) -> list[tuple[Any, ...]]:
    """parse_board as tuples in POSTING_FIELDS order: the shape a Spark struct UDF returns."""
    return [tuple(row[f] for f in POSTING_FIELDS) for row in parse_board(source, raw_json)]
