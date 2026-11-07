-- Guards against an empty or broken load: there must be at least 1,000 open postings
-- (about 15,200 in prod on Nov 6). Returns a row (= fails) when there are fewer.
select count_if(is_open) as open_postings
from {{ ref('fct_postings') }}
having count_if(is_open) < 1000
