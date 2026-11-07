-- Daily labeling queue (Databricks SQL editor).
-- 40 open postings that you could apply to: US locations, full-time or contract, not far
-- above your level, at employers that file H-1Bs. Up to 6 from each of your five role
-- families (so no one family crowds out the rest), plus 10 others so the fit model also
-- learns what a clear "skip" looks like. Newest postings come first.
-- Set the parameter day = 1 on your first labeling day, 2 the next, and so on.
-- Paste the seven columns into "Seed Labels (private)" > Daily Labels, columns B to H.
-- These rules move into dbt as is_us, role_family and seniority columns (T15).

WITH filers AS (
  SELECT DISTINCT company FROM workspace.jobradar_silver.employer_matches
),
open_postings AS (
  SELECT p.source, p.posting_id, p.company, p.title, p.location, p.url, p.first_seen,
         CASE
           WHEN p.title RLIKE '(?i)business systems|systems analyst|\\berp\\b|netsuite|\\bsap\\b|oracle|workday|salesforce|coupa|enterprise applications|financ(e|ial) systems' THEN 'Business systems / ERP'
           WHEN p.title RLIKE '(?i)integration|solutions? (engineer|architect)|\\bconsultant\\b|consulting|implementation|forward deployed|customer engineer' THEN 'Integration / solutions'
           WHEN p.title RLIKE '(?i)data engineer|analytics engineer|\\betl\\b|data warehouse|business intelligence|\\bbi\\b|power bi|tableau|data analyst|analytics|data scien|machine learning|\\bml\\b|\\bai\\b|artificial intelligence' THEN 'Data / BI / AI'
           WHEN p.title RLIKE '(?i)software (engineer|developer)|backend|full stack|python|application developer' THEN 'Software'
           WHEN p.title RLIKE '(?i)technical program manager|program analyst|product owner|technical product manager' THEN 'Technical program / product'
           ELSE 'Other'
         END AS role_family
  FROM workspace.jobradar_silver.postings AS p
  JOIN filers USING (company)
  WHERE p.is_open
    -- US roles only
    AND (
          p.location ILIKE '%United States%'
       OR p.location RLIKE ', (AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\\b'
       OR p.location RLIKE '(?i)remote.*(\\bUS\\b|USA|United States)'
       OR p.location RLIKE '(?i)^(San Francisco|New York|Seattle|Austin|Chicago|Boston|Denver|Mountain View|Palo Alto)'
    )
    -- full-time or contract only: no interns, students or part-time
    AND coalesce(p.employment_type, 'FullTime') IN ('FullTime', 'Contract')
    AND NOT p.title RLIKE '(?i)\\bintern\\b|internship|co-op|apprentice|\\bstudent\\b'
    -- not far above your level
    AND NOT p.title RLIKE '(?i)\\bstaff\\b|principal|director|\\bhead\\b|\\bvp\\b|vice president'
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY role_family ORDER BY first_seen DESC, xxhash64(posting_id)) AS rn
  FROM open_postings
)
SELECT source, posting_id, company, title, location, url, role_family
FROM ranked
WHERE (role_family <> 'Other' AND rn BETWEEN (:day - 1) * 6 + 1 AND :day * 6)
   OR (role_family =  'Other' AND rn BETWEEN (:day - 1) * 10 + 1 AND :day * 10)
ORDER BY role_family, company, title;
