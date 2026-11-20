"""Tag every open US posting with the skills it asks for (CR09: resume match for visitors).

Runs in the daily cloud job after dbt. It reads each open posting's title and description,
finds the tracked skills with the same patterns the assistant uses (agent/skills.py), and
replaces workspace.jobradar_ml.posting_skills(posting_key, skills, n_skills, indexed_at).
dbt joins it into fct_postings, so the API can rank fresh jobs for a visitor's skills inside
Databricks without reading descriptions on each request.

skills is stored as "|SQL|Python|dbt|" so a skill can be matched with instr(skills, '|SQL|').
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from jobradar.agent.skills import SKILLS, find_skills
from jobradar.fit.features import gold_table

from .scores import SCORES_SCHEMA

SKILLS_TABLE = f"{SCORES_SCHEMA}.posting_skills"
_KEY_OK = re.compile(r"^[a-z]+:[A-Za-z0-9_-]+$")
BATCH = 1000


def skills_field(skills: Iterable[str]) -> str:
    """Skill names as '|A|B|' (sorted), or '' when there are none."""
    names = sorted(set(skills))
    return f"|{'|'.join(names)}|" if names else ""


def _literal(text: str) -> str:
    """A SQL string literal. Skill names come from the fixed list in skills.py; quotes are
    escaped anyway."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


Posting = tuple[str, str | None, str | None]  # posting_key, title, description


def index_rows(postings: Sequence[Posting]) -> list[tuple[str, str, int]]:
    """(posting_key, title, description) -> (posting_key, skills field, number of skills)."""
    rows = []
    for key, title, description in postings:
        found = find_skills(f"{title or ''}\n{description or ''}")
        rows.append((key, skills_field(found), len(found)))
    return rows


def values_sql(rows: Sequence[tuple[str, str, int]]) -> list[str]:
    values = []
    for key, field, n in rows:
        if not _KEY_OK.match(key):
            raise ValueError(f"unexpected posting key {key!r}")
        unknown = [s for s in field.strip("|").split("|") if s and s not in SKILLS]
        if unknown:
            raise ValueError(f"unknown skills {unknown}")
        values.append(f"('{key}', {_literal(field)}, {int(n)}, current_timestamp())")
    return [
        f"INSERT INTO {SKILLS_TABLE} VALUES " + ", ".join(values[i : i + BATCH])
        for i in range(0, len(values), BATCH)
    ]


def fetch_open_postings(connection, env: str = "prod") -> list[tuple[str, str, str]]:
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT posting_key, title, description_text FROM {gold_table(env)} "
            "WHERE is_open AND is_us"
        )
        return [tuple(r) for r in cur.fetchall()]


def upload_skills(connection, rows: Sequence[tuple[str, str, int]]) -> int:
    statements = values_sql(rows)
    with connection.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCORES_SCHEMA}")
        cur.execute(
            f"CREATE OR REPLACE TABLE {SKILLS_TABLE} ("
            "posting_key STRING NOT NULL, skills STRING NOT NULL, n_skills INT NOT NULL, "
            "indexed_at TIMESTAMP NOT NULL) "
            "COMMENT 'Tracked skills each open US posting asks for (jobradar skills-index)'"
        )
        for sql in statements:
            cur.execute(sql)
    return len(rows)
