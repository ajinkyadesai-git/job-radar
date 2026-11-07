-- Every row in the Today list must be open, US, full-time or contract, at your level, at a
-- sponsoring company and recent. Returns the rows that break a rule.
select n.posting_key, n.title, n.location
from {{ ref('mart_new_postings') }} as n
join {{ ref('fct_postings') }} as p using (posting_key)
where not p.is_open
   or not p.is_us
   or not p.is_fte_or_contract
   or not p.is_target_level
   or p.is_intern
   or not p.is_sponsor
   or p.first_seen < date_sub(current_date(), 7)
