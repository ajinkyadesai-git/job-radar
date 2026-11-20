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
