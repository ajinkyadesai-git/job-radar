{{ config(severity = 'warn') }}
-- If the visa rules drop more than 25% of open US postings, a pattern is probably too broad.
-- Warns (does not fail); check gold.audit_dropped_postings to see what matched.
select
    count_if(has_visa_blocker or is_perm_style_ad)                           as flagged,
    count(*)                                                                 as open_us,
    round(count_if(has_visa_blocker or is_perm_style_ad) / count(*), 3)      as share
from {{ ref('fct_postings') }}
where is_open and is_us
having count_if(has_visa_blocker or is_perm_style_ad) / count(*) > 0.25
