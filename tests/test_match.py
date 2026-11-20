"""Resume match for visitors (CR09): skill tags per posting, the guarded query, the API."""

import pytest

from jobradar.agent.skills import SKILLS
from jobradar.agent.sql_guard import check
from jobradar.fit.skills_index import index_rows, skills_field, values_sql
from jobradar.queries import match_sql


def test_postings_are_tagged_with_the_skills_they_ask_for():
    rows = index_rows([
        ("ashby:1", "Data Engineer", "We use SQL, Python and dbt daily."),
        ("ashby:2", "Account Executive", "Quota and pipeline."),
    ])  # fmt: skip
    assert rows[0] == ("ashby:1", "|Python|SQL|dbt|", 3)
    assert rows[1] == ("ashby:2", "", 0)
    assert skills_field(["SQL", "Python", "SQL"]) == "|Python|SQL|"


def test_upload_sql_rejects_odd_keys_and_unknown_skills():
    sql = values_sql([("ashby:1", "|C#|Python|", 2)])[0]
    assert "('ashby:1', '|C#|Python|', 2, current_timestamp())" in sql
    with pytest.raises(ValueError, match="posting key"):
        values_sql([("ashby:1'); drop table x; --", "", 0)])
    with pytest.raises(ValueError, match="unknown skills"):
        values_sql([("ashby:1", "|SQL|'); drop table x; --|", 1)])


def test_match_query_is_built_from_known_skills_only_and_passes_the_guard():
    sql = match_sql(["SQL", "Python", "C#"], years=3, role_family="Software", limit=10)
    guarded = check(sql, env="prod").sql
    assert "workspace.jobradar_gold.fct_postings" in guarded
    assert "'|C#|'" in guarded and "role_family = 'Software'" in guarded
    assert "<= 5" in guarded  # years + 2
    for bad in (
        lambda: match_sql(["SQL') or 1=1 --"], 3),
        lambda: match_sql([], 3),
        lambda: match_sql(["SQL"], 31),
        lambda: match_sql(["SQL"], 3, role_family="Other"),
        lambda: match_sql(["SQL"], 3, limit=500),
    ):
        with pytest.raises(ValueError):
            bad()


def test_every_skill_name_is_safe_inside_the_match_query():
    for name in SKILLS:
        assert "'" not in name and "|" not in name
    check(match_sql(list(SKILLS)[:40], 5), env="prod")


def test_match_hides_titles_above_the_visitors_level_and_smooths_short_skill_lists():
    from jobradar.queries import match_sql

    junior = match_sql(["Python", "SQL"], years=2)
    assert "seniority not in ('Staff / principal', 'Director+', 'Senior')" in junior
    assert "(n_skills + 3)" in junior  # 3 of 3 skills no longer ties 7 of 7
    mid = match_sql(["Python", "SQL"], years=5)
    assert "'Senior'" not in mid and "'Staff / principal'" in mid
    assert "seniority not in" not in match_sql(["Python"], years=10)
    assert "copy = 1" in junior  # a job posted in several cities shows once
