-- The "Today" list: open US full-time or contract roles at your level (no interns, nothing
-- Staff / principal or above) at companies that sponsor, first seen in the last 7 days.
-- Postings that say they won't sponsor, or read like green-card (PERM) ads, are left out;
-- gold.audit_dropped_postings lists them with the phrase that matched.
-- The first load day is left out: everything was "new" that day.
with first_load as (
    select min(first_seen) as day from {{ ref('stg_postings') }}
)
select
    p.posting_key,
    p.source,
    p.posting_id,
    p.company,
    p.company_name,
    p.title,
    p.location,
    p.url,
    p.role_family,
    p.seniority,
    p.employment_type,
    p.salary_min_yearly_usd,
    p.salary_max_yearly_usd,
    p.first_seen,
    p.company_lca_filings,
    p.company_certified_rate,
    p.company_median_filed_wage,
    p.fit_score
from {{ ref('fct_postings') }} as p
cross join first_load
where p.is_open
  and p.is_us
  and p.is_fte_or_contract
  and p.is_target_level
  and not p.has_visa_blocker
  and not p.is_perm_style_ad
  and p.is_sponsor
  and p.first_seen > first_load.day
  and p.first_seen >= date_sub(current_date(), 7)
