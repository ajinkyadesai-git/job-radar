{{ config(severity = 'warn') }}
-- Boards sometimes publish a salary range backwards. Warn, do not fail: it is the source's data.
select posting_key, company, title, salary_min, salary_max
from {{ ref('fct_postings') }}
where salary_min > salary_max
