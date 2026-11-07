-- Employer matching must not silently get worse. Of the companies whose job boards we load,
-- at least 90% must be linked to DOL filings (72 of 74 on Nov 6). Returns a row (= fails)
-- when the rate drops below 90%, for example after a bad alias or a company rename.
with loaded as (
    select company, is_sponsor
    from {{ ref('dim_employer') }}
    where first_seen is not null          -- has at least one posting
)
select
    count(*)                                   as companies_loaded,
    count_if(is_sponsor)                       as companies_matched,
    round(count_if(is_sponsor) / count(*), 3)  as match_rate
from loaded
having count(*) = 0 or count_if(is_sponsor) / count(*) < 0.9
