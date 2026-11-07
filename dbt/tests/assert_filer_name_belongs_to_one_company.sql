-- A DOL filer name may be linked to only one tracked company; two would double-count filings.
select employer_name, trade_name_dba, count(distinct company) as companies
from {{ ref('stg_employer_matches') }}
group by employer_name, trade_name_dba
having count(distinct company) > 1
