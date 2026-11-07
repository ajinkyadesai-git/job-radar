-- One row per posting, with the business rules applied once.
select
    concat(source, ':', posting_id)                       as posting_key,
    source,
    posting_id,
    company,
    title,
    department,
    team,
    location,
    is_remote,
    workplace_type,
    employment_type,
    url,
    published_at,
    description_text,
    salary_min,
    salary_max,
    salary_currency,
    salary_interval,
    salary_source,
    first_seen,
    last_seen,
    is_open,
    closed_on,
    {{ is_us_location('location') }}                      as is_us,
    {{ role_family('title') }}                            as role_family,
    {{ seniority('title') }}                              as seniority,
    {{ is_intern('title', 'employment_type') }}           as is_intern,
    coalesce(employment_type, 'FullTime') in ('FullTime', 'Contract')
        and not {{ is_intern('title', 'employment_type') }} as is_fte_or_contract,
    -- Yearly USD salary where the board gives one; hourly is scaled by 2,080 hours.
    case
        when coalesce(salary_currency, 'USD') <> 'USD' then null
        when upper(salary_interval) in ('YEAR', 'YEARLY', 'ANNUAL') then salary_min
        when upper(salary_interval) in ('HOUR', 'HOURLY') then salary_min * 2080
    end                                                   as salary_min_yearly_usd,
    case
        when coalesce(salary_currency, 'USD') <> 'USD' then null
        when upper(salary_interval) in ('YEAR', 'YEARLY', 'ANNUAL') then salary_max
        when upper(salary_interval) in ('HOUR', 'HOURLY') then salary_max * 2080
    end                                                   as salary_max_yearly_usd,
    datediff(coalesce(closed_on, last_seen), first_seen)  as days_open
from {{ source('silver', 'postings') }}
