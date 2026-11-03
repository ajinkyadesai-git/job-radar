import json
from pathlib import Path

import pytest

from jobradar.lakehouse.postings import (
    POSTING_FIELDS,
    html_to_text,
    parse_board,
    parse_board_rows,
    salary_from_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _raw(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_greenhouse_board_gives_one_row_per_job():
    rows = parse_board("greenhouse", _raw("greenhouse_board.json"))

    assert [r["posting_id"] for r in rows] == ["4000001", "4000002"]
    first = rows[0]
    assert first["title"] == "Data Engineer, Platform"
    assert first["department"] == "Data"
    assert first["location"] == "San Francisco, CA"
    assert first["is_remote"] is False
    assert first["description_text"] == "Build pipelines."
    assert first["published_at"] == "2026-10-01T10:00:00-04:00"
    assert rows[1]["is_remote"] is True  # "Remote - US"


def test_ashby_board_reads_structured_salary():
    rows = parse_board("ashby", _raw("ashby_board.json"))

    assert len(rows) == 1
    row = rows[0]
    assert row["posting_id"] == "b1f2c3d4-0000-4000-8000-000000000001"
    assert row["team"] == "Data Platform"
    assert row["workplace_type"] == "Hybrid"
    assert (row["salary_min"], row["salary_max"]) == (180000.0, 230000.0)
    assert (row["salary_currency"], row["salary_interval"]) == ("USD", "YEAR")
    assert row["salary_source"] == "structured"


def test_every_row_has_exactly_the_declared_fields():
    for source, name in [("greenhouse", "greenhouse_board.json"), ("ashby", "ashby_board.json")]:
        for row in parse_board(source, _raw(name)):
            assert tuple(row) == POSTING_FIELDS


def test_salary_found_in_description_when_not_structured():
    board = json.loads(_raw("greenhouse_board.json"))
    board["jobs"][0]["content"] = (
        "&lt;p&gt;The base pay range for this role is $170,000&amp;mdash;$215,000 USD.&lt;/p&gt;"
    )
    row = parse_board("greenhouse", json.dumps(board))[0]

    assert (row["salary_min"], row["salary_max"]) == (170000.0, 215000.0)
    assert row["salary_source"] == "description"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pay: $150,000 - $200,000 per year", (150000.0, 200000.0)),
        ("Range $140K to $180K plus equity", (140000.0, 180000.0)),
        ("Hourly: $45 - $60 per hour", None),
        ("No pay information.", None),
        (None, None),
    ],
)
def test_salary_from_text(text, expected):
    assert salary_from_text(text) == expected


def test_html_to_text_keeps_paragraph_breaks():
    escaped = (
        "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;We build&amp;nbsp;things.&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"
    )
    # One line per block, so the RAG step can split descriptions into sections later.
    assert html_to_text(escaped) == "About\nWe build things.\nSQL"
    assert html_to_text("") is None


def test_unknown_source_is_an_error():
    with pytest.raises(KeyError):
        parse_board("lever", "{}")


def test_rows_for_spark_are_tuples_in_field_order():
    rows = parse_board_rows("ashby", _raw("ashby_board.json"))
    assert len(rows[0]) == len(POSTING_FIELDS)
    assert rows[0][POSTING_FIELDS.index("title")] == "Senior Data Engineer"
