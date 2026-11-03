-- Daily labeling queue (Databricks SQL editor).
-- 40 open postings: 30 with data, analytics or AI titles and 10 others, so the fit model
-- also learns what a clear "skip" looks like. Newest postings come first.
-- Set the parameter day = 1 on your first labeling day, 2 the next, and so on.
-- Paste the result into "Seed Labels (private)" > Daily Labels, columns B to G.

WITH open_postings AS (
  SELECT source, posting_id, company, title, location, url, first_seen,
         regexp_like(
           lower(title),
           'data|analytics|machine learning|\\bml\\b|\\bai\\b|artificial intelligence|forward deployed|solutions engineer|business intelligence|\\bbi\\b|decision scien|insights'
         ) AS relevant
  FROM workspace.jobradar_dev_silver.postings
  WHERE is_open
),
ranked AS (
  SELECT *,
         row_number() OVER (
           PARTITION BY relevant ORDER BY first_seen DESC, xxhash64(posting_id)
         ) AS rn
  FROM open_postings
)
SELECT source, posting_id, company, title, location, url
FROM ranked
WHERE (relevant AND rn BETWEEN (:day - 1) * 30 + 1 AND :day * 30)
   OR (NOT relevant AND rn BETWEEN (:day - 1) * 10 + 1 AND :day * 10)
ORDER BY relevant DESC, company, title;
