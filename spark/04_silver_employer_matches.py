# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: employer matches
# MAGIC
# MAGIC Links each tracked company (job boards) to the employer names it files under at DOL.
# MAGIC
# MAGIC 1. **Exact:** normalized company name = normalized filer name or "doing business as" name.
# MAGIC 2. **Alias:** rows marked `approved` in `config/employer_aliases.csv`, checked by a person.
# MAGIC
# MAGIC Outputs `<env>_silver.employer_matches` (one row per matched filer name) and
# MAGIC `<env>_silver.employer_match_candidates`: similar filer names for a person to review.
# MAGIC Nothing is matched by similarity alone.

# COMMAND ----------

import os
import re
import sys

repo = os.path.abspath(os.path.join(os.getcwd(), ".."))
sys.path.insert(0, os.path.join(repo, "src"))

from pyspark import cloudpickle
from pyspark.sql import functions as F

import jobradar.lakehouse.employers as employers
from jobradar.lakehouse.paths import schema

cloudpickle.register_pickle_by_value(employers)

dbutils.widgets.text("env", "dev")
env = dbutils.widgets.get("env")
silver = schema(env, "silver")
lca, postings = f"{silver}.lca_filings", f"{silver}.postings"
matches_table = f"{silver}.employer_matches"
candidates_table = f"{silver}.employer_match_candidates"

# Tracked companies from config/companies.yaml (flow-style rows: { slug: x, name: Y, ... }).
with open(os.path.join(repo, "config", "companies.yaml")) as f:
    companies_yaml = f.read()
companies = re.findall(r"slug:\s*([\w-]+),\s*name:\s*([^,}]+?)\s*,", companies_yaml)
slugs = {slug for slug, _ in companies}
aliases = employers.load_aliases(os.path.join(repo, "config", "employer_aliases.csv"), slugs)
print(
    f"{len(companies)} companies, {len(aliases)} alias rows "
    f"({sum(a.status == 'approved' for a in aliases)} approved)"
)

# COMMAND ----------

keys = [
    (slug, key, "exact") for slug, name in companies for key in employers.company_keys(slug, name)
]
keys += [(a.company_slug, a.normalized, "alias") for a in aliases if a.status == "approved"]
company_keys = spark.createDataFrame(keys, "company string, employer_key string, method string")

normalize = F.udf(employers.normalize_employer, "string")
filers = (
    spark.table(lca)
    .groupBy("employer_name", "trade_name_dba")
    .agg(
        F.count("*").alias("filings"),
        F.count_if(F.col("case_status") == "Certified").alias("certified"),
        F.percentile_approx("wage_from_yearly", 0.5).alias("median_yearly_wage"),
        F.max("decision_date").alias("last_decision"),
    )
    .withColumn("name_key", normalize("employer_name"))
    .withColumn("dba_key", normalize("trade_name_dba"))
)
filers.createOrReplaceTempView("filers")
company_keys.createOrReplaceTempView("company_keys")

# One row per (company, filer name); exact wins over alias when both apply.
spark.sql(f"""
CREATE OR REPLACE TABLE {matches_table}
COMMENT 'Tracked company to DOL filer name, by exact normalized match or approved alias.'
AS
SELECT company, employer_name, trade_name_dba, method, filings, certified,
       median_yearly_wage, last_decision
FROM (
  SELECT k.company, f.*, k.method,
         row_number() OVER (PARTITION BY k.company, f.employer_name, f.trade_name_dba
                            ORDER BY CASE k.method WHEN 'exact' THEN 0 ELSE 1 END) AS rn
  FROM filers f
  JOIN company_keys k ON k.employer_key IN (f.name_key, f.dba_key)
)
WHERE rn = 1
""")

# COMMAND ----------

# Review list: filer names that start with a company's name, plus every proposed alias,
# with how many filings each really has. A proposed alias with 0 filings is a wrong name.
spark.sql(f"""
CREATE OR REPLACE TABLE {candidates_table}
COMMENT 'Filer names a person should review before approving an alias.'
AS
WITH prefix AS (
  SELECT k.company, f.employer_name, f.trade_name_dba, f.filings, f.certified,
         'similar name' AS why
  FROM filers f
  JOIN company_keys k
    ON k.method = 'exact'
   AND (f.name_key LIKE concat(k.employer_key, ' %') OR f.dba_key LIKE concat(k.employer_key, '%'))
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY company ORDER BY filings DESC) AS rn FROM prefix
)
SELECT company, employer_name, trade_name_dba, filings, certified, why
FROM ranked
WHERE rn <= 8
  AND NOT EXISTS (SELECT 1 FROM {matches_table} m
                  WHERE m.company = ranked.company AND m.employer_name = ranked.employer_name)
""")

proposed = spark.createDataFrame(
    [(a.company_slug, a.dol_employer_name, a.normalized, a.status) for a in aliases],
    "company string, alias_name string, alias_key string, status string",
)
proposed.createOrReplaceTempView("alias_rows")
display(
    spark.sql("""
    SELECT a.company, a.alias_name, a.status,
           coalesce(sum(f.filings), 0) AS filings_found,
           array_join(collect_set(f.employer_name), ' | ') AS filer_names_found
    FROM alias_rows a LEFT JOIN filers f ON a.alias_key IN (f.name_key, f.dba_key)
    GROUP BY ALL
    ORDER BY a.company
    """)
)

# COMMAND ----------

display(spark.table(candidates_table).orderBy("company", F.desc("filings")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Checks and match rate

# COMMAND ----------

dupes = spark.sql(f"""
    SELECT count(*) FROM (
      SELECT employer_name, trade_name_dba FROM {matches_table}
      GROUP BY ALL HAVING count(DISTINCT company) > 1)""").first()[0]
print(f"{'OK  ' if dupes == 0 else 'FAIL'} filer names matched to more than one company: {dupes}")
assert dupes == 0

all_companies = spark.createDataFrame(companies, "company string, name string")
all_companies.createOrReplaceTempView("all_companies")
summary = spark.sql(f"""
    WITH open_counts AS (
      SELECT company, count(*) AS open_postings FROM {postings} WHERE is_open GROUP BY company
    ),
    by_company AS (
      SELECT c.company, c.name,
             CASE WHEN count(m.method) = 0 THEN 'unmatched'
                  ELSE array_join(array_sort(collect_set(m.method)), '+') END AS method,
             coalesce(sum(m.filings), 0)   AS filings,
             coalesce(sum(m.certified), 0) AS certified,
             max(m.median_yearly_wage)     AS median_yearly_wage_top_filer
      FROM all_companies c LEFT JOIN {matches_table} m USING (company)
      GROUP BY c.company, c.name
    )
    SELECT b.*, coalesce(o.open_postings, 0) AS open_postings
    FROM by_company b LEFT JOIN open_counts o USING (company)
    ORDER BY filings DESC
""")
summary.createOrReplaceTempView("match_summary")
display(summary)

rate = spark.sql("""
    SELECT count_if(filings > 0)                         AS companies_matched,
           count(*)                                      AS companies,
           sum(filings)                                  AS filings_linked,
           round(100 * sum(CASE WHEN filings > 0 THEN open_postings END)
                 / sum(open_postings), 1)                AS pct_open_postings_covered
    FROM match_summary
""").first()
print(
    f"Match rate: {rate.companies_matched} of {rate.companies} companies; "
    f"{rate.filings_linked} filings linked; "
    f"{rate.pct_open_postings_covered}% of open postings are at a matched employer"
)
