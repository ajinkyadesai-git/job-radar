-- Every posting Job Radar has seen, open or closed, with business rules and sponsor flag.
select
    p.*,
    c.name                         as company_name,
    s.company is not null          as is_sponsor,     -- company files H-1B/E-3 LCAs
    s.filings                      as company_lca_filings,
    s.certified_rate               as company_certified_rate,
    s.median_filed_wage            as company_median_filed_wage,
    f.fit_score                    -- 0-1, your fit model; null if not scored yet
from {{ ref('stg_postings') }} as p
left join {{ source('ml', 'fit_scores') }} as f on f.posting_key = p.posting_key
left join {{ ref('companies') }} as c on c.slug = p.company
left join (
    select company, filings, certified_rate, median_filed_wage
    from {{ ref('dim_employer') }}
    where filings > 0
) as s on s.company = p.company
