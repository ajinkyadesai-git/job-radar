-- DOL LCA filings, with the tracked company attached when the filer is one of ours.
select
    l.*,
    m.company,
    m.match_method
from {{ ref('stg_lca_filings') }} as l
left join {{ ref('stg_employer_matches') }} as m
    on  l.employer_name  = m.employer_name
    and l.trade_name_dba <=> m.trade_name_dba
