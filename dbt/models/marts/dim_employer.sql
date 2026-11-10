-- One row per tracked company: its board, how many jobs are open, and how it sponsors.
with postings as (
    select
        company,
        count_if(is_open)                         as open_postings,
        count_if(is_open and is_us)               as open_us_postings,
        min(first_seen)                           as first_seen
    from {{ ref('stg_postings') }}
    group by company
),
lca as (
    select
        company,
        count(*)                                  as filings,
        count_if(is_certified)                    as certified,
        percentile_approx(wage_from_yearly, 0.5)  as median_filed_wage,
        max(decision_date)                        as last_decision,
        avg(case when is_h1b_dependent then 1.0 else 0.0 end) as h1b_dependent_share,
        array_join(slice(array_sort(collect_set(employer_name)), 1, 5), ' | ') as filer_names
    from {{ ref('fct_lca') }}
    where company is not null
    group by company
)
select
    c.slug                                        as company,
    c.name                                        as company_name,
    c.source                                      as board_source,
    c.board_token,
    coalesce(p.open_postings, 0)                  as open_postings,
    coalesce(p.open_us_postings, 0)               as open_us_postings,
    p.first_seen,
    coalesce(l.filings, 0) > 0                    as is_sponsor,
    coalesce(l.filings, 0)                        as filings,
    coalesce(l.certified, 0)                      as certified,
    round(l.certified / nullif(l.filings, 0), 3)  as certified_rate,
    l.median_filed_wage,
    l.last_decision,
    round(l.h1b_dependent_share, 3)               as h1b_dependent_share,
    -- H-1B dependent employers (mostly staffing and IT consulting firms) file for most of
    -- their staff; DOL flags them on each filing.
    coalesce(l.h1b_dependent_share, 0) >= 0.5     as is_h1b_dependent_employer,
    l.filer_names
from {{ ref('companies') }} as c
left join postings as p on p.company = c.slug
left join lca      as l on l.company = c.slug
where c.enabled
