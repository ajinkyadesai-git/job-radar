{{ config(materialized='view') }}
-- Why each open US posting was dropped by a visa rule, with the exact phrase that matched,
-- so false positives ("unable to sponsor for this role, but...") are easy to spot and fix.
select
    posting_key,
    company,
    title,
    location,
    first_seen,
    case when has_visa_blocker then 'visa blocker' else 'green-card style ad' end as dropped_because,
    coalesce(visa_blocker_match, perm_ad_match)                                   as matched_text,
    url
from {{ ref('fct_postings') }}
where is_open
  and is_us
  and (has_visa_blocker or is_perm_style_ad)
