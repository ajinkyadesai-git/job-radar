-- first_seen <= last_seen, and a closed posting has a closed_on on or after first_seen.
select posting_key, first_seen, last_seen, closed_on, is_open
from {{ ref('fct_postings') }}
where last_seen < first_seen
   or (not is_open and (closed_on is null or closed_on < first_seen))
   or (is_open and closed_on is not null)
