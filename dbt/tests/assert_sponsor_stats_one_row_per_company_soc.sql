-- Fails if a company and SOC code appear more than once in mart_sponsor_stats.
select company, soc_code, count(*) as n
from {{ ref('mart_sponsor_stats') }}
group by company, soc_code
having count(*) > 1
