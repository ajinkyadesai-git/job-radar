-- Per company: certified <= filings, open US jobs <= open jobs, approval rate between 0 and 1.
select company, filings, certified, open_postings, open_us_postings, certified_rate
from {{ ref('dim_employer') }}
where certified > filings
   or open_us_postings > open_postings
   or certified_rate < 0 or certified_rate > 1
