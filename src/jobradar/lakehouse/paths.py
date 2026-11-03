"""Names and raw-file path rules shared by the ingest and the Spark jobs.

The ingest writes raw files with ``jobradar.ingest.pipeline.raw_key``. The bronze job reads
the same files back and parses source, company, load date and hash out of the path. Keeping
the pattern here, with a test that round-trips ``raw_key``, means the two sides cannot drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

CATALOG = "workspace"
ENVS = ("dev", "prod")
BOARD_SOURCES = ("greenhouse", "ashby")

# Matches the end of a full path such as
# s3://bucket/dev/raw/greenhouse/anthropic/load_date=2026-11-02/0123456789abcdef.json
RAW_BOARD_FILE_PATTERN = (
    r"/raw/(greenhouse|ashby)/([^/]+)/load_date=(\d{4}-\d{2}-\d{2})/([0-9a-f]{16})\.json$"
)
_RAW_BOARD_FILE_RE = re.compile(RAW_BOARD_FILE_PATTERN)


@dataclass(frozen=True)
class RawBoardFile:
    source: str
    company: str
    load_date: date
    content_hash: str


def parse_raw_board_path(path: str) -> RawBoardFile | None:
    """Parse a raw board file path; return None if it is not one."""
    m = _RAW_BOARD_FILE_RE.search(path)
    if not m:
        return None
    source, company, load_date, content_hash = m.groups()
    return RawBoardFile(source, company, date.fromisoformat(load_date), content_hash)


def schema_prefix(env: str) -> str:
    """dev tables live in jobradar_dev_*, prod tables in jobradar_* (see Technical Design)."""
    if env not in ENVS:
        raise ValueError(f"env must be one of {ENVS}, got {env!r}")
    return "jobradar_dev" if env == "dev" else "jobradar"


def schema(env: str, layer: str) -> str:
    """Fully qualified schema, for example workspace.jobradar_dev_bronze."""
    if layer not in ("bronze", "silver", "gold", "ops"):
        raise ValueError(f"unknown layer {layer!r}")
    return f"{CATALOG}.{schema_prefix(env)}_{layer}"


def raw_board_glob(bucket: str, env: str) -> str:
    """Every raw board file for one environment, for Spark or Auto Loader."""
    schema_prefix(env)  # validates env
    return f"s3://{bucket}/{env}/raw/{{{','.join(BOARD_SOURCES)}}}/*/load_date=*/*.json"
