from datetime import date

import pytest

from jobradar.config import BoardSource, Company
from jobradar.ingest.pipeline import raw_key
from jobradar.lakehouse.paths import (
    parse_raw_board_path,
    raw_board_glob,
    schema,
)


@pytest.mark.parametrize(
    ("source", "slug"),
    [(BoardSource.GREENHOUSE, "scale-ai"), (BoardSource.ASHBY, "openai")],
)
def test_bronze_parses_every_path_the_ingest_writes(source, slug):
    company = Company(slug=slug, name=slug, source=source, board_token=slug)
    sha = "0123456789abcdef" * 4
    key = f"s3://bucket/dev/{raw_key(company, date(2026, 11, 2), sha)}"

    parsed = parse_raw_board_path(key)

    assert parsed is not None
    assert parsed.source == source.value
    assert parsed.company == slug
    assert parsed.load_date == date(2026, 11, 2)
    assert parsed.content_hash == sha[:16]


@pytest.mark.parametrize(
    "path",
    [
        "s3://bucket/dev/state/greenhouse/anthropic.json",
        "s3://bucket/dev/ops/pipeline_runs/run_date=2026-11-02/run_id=x.jsonl",
        "s3://bucket/dev/raw/dol/fiscal_year=2026/quarter=Q1/file.xlsx",
    ],
)
def test_other_files_are_not_board_files(path):
    assert parse_raw_board_path(path) is None


def test_schema_names_follow_the_design():
    assert schema("dev", "bronze") == "workspace.jobradar_dev_bronze"
    assert schema("prod", "silver") == "workspace.jobradar_silver"
    with pytest.raises(ValueError):
        schema("staging", "bronze")


def test_raw_board_glob_covers_both_sources():
    assert raw_board_glob("b", "dev") == "s3://b/dev/raw/{greenhouse,ashby}/*/load_date=*/*.json"
