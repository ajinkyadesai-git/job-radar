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
