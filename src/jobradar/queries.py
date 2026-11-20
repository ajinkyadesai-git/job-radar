"""Fixed queries shared by the API and the MCP server.

Values put into the SQL come only from the fixed lists below; anything else is refused
before a query is built. The SQL still goes through the SQL guard when it runs.
"""

from __future__ import annotations

ROLE_FAMILIES = (
    "Data / BI / AI", "Software", "Integration / solutions", "Business systems / ERP",
    "Technical program / product", "Other",
)  # fmt: skip
REACH = ("Within reach", "Stretch")
TODAY_COLUMNS = (
    "posting_key, company_name, title, location, url, role_family, seniority, "
    "years_required, reach, salary_min_yearly_usd, salary_max_yearly_usd, first_seen, "
    "company_lca_filings, company_median_filed_wage, fit_score"
)


def today_sql(limit: int = 20, reach: str | None = None, role_family: str | None = None) -> str:
    """The Today list, best fit first. Raises ValueError for any value outside the lists."""
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit must be between 1 and 100")
    filters = []
    if reach:
        if reach not in REACH:
            raise ValueError(f"reach must be one of {REACH}")
        filters.append(f"reach = '{reach}'")
    if role_family:
        if role_family not in ROLE_FAMILIES:
            raise ValueError(f"role_family must be one of {ROLE_FAMILIES}")
        filters.append(f"role_family = '{role_family}'")
    where = f"where {' and '.join(filters)} " if filters else ""
    return (
        f"select {TODAY_COLUMNS} from mart_new_postings {where}"
        f"order by fit_score desc nulls last, first_seen desc limit {int(limit)}"
    )


# The Insights page (replaces the Tableau dashboard, CR16). Fixed queries, no user input.
INSIGHTS = {
    "jobs_by_family": """select coalesce(role_family, 'Other') as role_family,
            count(*) as open_jobs, count_if(fit_score >= 0.5) as good_fit
        from fct_postings where is_open and is_us
        group by 1 order by open_jobs desc""",
    "new_per_day": """select first_seen as day, count(*) as new_jobs
        from fct_postings where is_us and first_seen >= date_sub(current_date(), 30)
        group by first_seen order by first_seen""",
    "pay_by_family": """select coalesce(role_family, 'Other') as role_family,
            count(*) as with_salary,
            percentile_approx((salary_min_yearly_usd
                + coalesce(salary_max_yearly_usd, salary_min_yearly_usd)) / 2, 0.5)
                as median_posted_midpoint
        from fct_postings
        where is_open and is_us and salary_min_yearly_usd is not null
        group by 1 order by median_posted_midpoint desc""",
    "top_sponsors": """select company_name, filings, certified_rate, median_filed_wage,
            open_us_postings
        from dim_employer where filings > 0 order by filings desc limit 15""",
}

EMPLOYERS_SQL = """select company, company_name, board_source, open_us_postings, filings,
        certified_rate, median_filed_wage, is_h1b_dependent_employer
    from dim_employer order by open_us_postings desc, filings desc limit 100"""


# Resume match for visitors (CR09). The visitor's skills must be names from the fixed list in
# agent/skills.py, so they are safe to put in the SQL; years and limits are plain integers.
FRESH_DAYS = 14
MAX_MATCH_SKILLS = 40
MATCH_COLUMNS = (
    "posting_key, company_name, title, location, url, role_family, years_required, "
    "salary_min_yearly_usd, salary_max_yearly_usd, company_lca_filings, "
    "company_median_filed_wage, first_seen, skills, n_skills"
)


def match_sql(
    skills: list[str], years: int, role_family: str | None = None, limit: int = 25
) -> str:
    """Fresh tech jobs at H-1B sponsors, ranked by the share of each job's skills the visitor
    has. Raises ValueError for anything outside the allowed values."""
    from jobradar.agent.skills import SKILLS

    names = sorted(set(skills))
    if not 1 <= len(names) <= MAX_MATCH_SKILLS:
        raise ValueError(f"give between 1 and {MAX_MATCH_SKILLS} skills")
    unknown = [n for n in names if n not in SKILLS]
    if unknown:
        raise ValueError(f"unknown skills: {unknown[:5]}")
    if not 0 <= int(years) <= 30:
        raise ValueError("years must be between 0 and 30")
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit must be between 1 and 50")
    family = ""
    if role_family:
        if role_family not in ROLE_FAMILIES or role_family == "Other":
            raise ValueError(f"role_family must be one of {ROLE_FAMILIES[:-1]}")
        family = f"and role_family = '{role_family}' "
    hits = " + ".join(
        "case when instr(skills, '|" + n.replace("'", "") + "|') > 0 then 1 else 0 end"
        for n in names
    )
    return (
        f"select * from (select {MATCH_COLUMNS}, ({hits}) as matched from fct_postings "
        "where is_open and is_us and is_sponsor and is_fte_or_contract "
        "and not has_visa_blocker and not is_perm_style_ad "
        "and coalesce(role_family, 'Other') <> 'Other' "
        f"and first_seen >= date_sub(current_date(), {FRESH_DAYS}) "
        "and n_skills >= 3 "
        f"and coalesce(years_required, 0) <= {int(years) + 2} {family}) as m "
        "where matched > 0 "
        f"order by matched / n_skills desc, matched desc, first_seen desc limit {int(limit)}"
    )
