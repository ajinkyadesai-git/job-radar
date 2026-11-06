-- Milestone 2 gate: "One query lists new roles at employers that file."
-- New open postings (first seen in the last 7 days, after the first load) at companies matched to DOL filings,
-- with what that employer filed: number of filings, certified share and median yearly wage.
-- Run in the Databricks SQL editor.

WITH filer_stats AS (
  SELECT company,
         sum(filings)                                   AS dol_filings,
         round(100 * sum(certified) / sum(filings), 0)  AS pct_certified,
         max(median_yearly_wage)                        AS median_yearly_wage
  FROM workspace.jobradar_dev_silver.employer_matches
  GROUP BY company
)
SELECT p.first_seen,
       p.company,
       p.title,
       p.location,
       p.salary_min,
       p.salary_max,
       f.dol_filings,
       f.pct_certified,
       f.median_yearly_wage AS employer_median_filed_wage,
       p.url
FROM workspace.jobradar_dev_silver.postings AS p
JOIN filer_stats AS f USING (company)
WHERE p.is_open
  AND p.first_seen >= date_sub(current_date(), 7)
  AND p.first_seen > (SELECT min(first_seen) FROM workspace.jobradar_dev_silver.postings)
  -- Keep US roles only: DOL filings cover US jobs.
  AND (
        p.location ILIKE '%United States%'
          OR p.location RLIKE ', (AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\\b'          -- "San Francisco, CA"
     OR p.location RLIKE '(?i)remote.*(\\bUS\\b|USA|United States)'
     OR p.location RLIKE '(?i)^(San Francisco|New York|Seattle|Austin|Chicago|Boston|Denver)'
  )
ORDER BY p.first_seen DESC, f.dol_filings DESC, p.company, p.title;