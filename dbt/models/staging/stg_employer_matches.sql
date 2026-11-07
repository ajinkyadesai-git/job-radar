-- Tracked company to DOL filer name (one row per filer name).
select
    company,
    employer_name,
    trade_name_dba,
    method as match_method,
    filings,
    certified,
    median_yearly_wage,
    last_decision
from {{ source('silver', 'employer_matches') }}
