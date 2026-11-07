-- How each tracked company sponsors, by occupation (SOC code): volume, approval and pay.
select
    company,
    soc_code,
    any_value(soc_title)                          as soc_title,
    count(*)                                      as filings,
    count_if(is_certified)                        as certified,
    round(count_if(is_certified) / count(*), 3)   as certified_rate,
    percentile_approx(wage_from_yearly, 0.25)     as p25_filed_wage,
    percentile_approx(wage_from_yearly, 0.5)      as median_filed_wage,
    percentile_approx(wage_from_yearly, 0.75)     as p75_filed_wage,
    max(decision_date)                            as last_decision,
    array_join(slice(array_sort(collect_set(job_title)), 1, 5), ' | ') as sample_titles
from {{ ref('fct_lca') }}
where company is not null and soc_code is not null
group by company, soc_code
