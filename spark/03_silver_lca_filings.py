# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: LCA filings
# MAGIC
# MAGIC Loads the DOL LCA disclosure files landed by `jobradar dol-upload` into
# MAGIC `<env>_silver.lca_filings`, one row per case, with typed columns and the offered wage
# MAGIC converted to a yearly figure so employers and roles can be compared.
# MAGIC
# MAGIC - **MERGE on `case_number`:** a case that appears in more than one quarterly file keeps
# MAGIC   its latest version, so loading a file twice, or overlapping files, never duplicates.
# MAGIC - **No personal data:** the upload step already removed contact names, emails and phones.

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "src")))

from pyspark.sql import Window
from pyspark.sql import functions as F

from jobradar.lakehouse.paths import schema

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("bucket", "job-radar-ad-4312")
env = dbutils.widgets.get("env")
bucket = dbutils.widgets.get("bucket")

silver = f"{schema(env, 'silver')}.lca_filings"
base = f"s3://{bucket}/{env}/raw/dol/"
print(f"env={env}\nsource={base}*/*/lca_selected.parquet\ntable={silver}")

# COMMAND ----------

# Hours or weeks to a year, for comparing offered wages. Unknown units stay null.
YEARLY = {"Year": 1, "Month": 12, "Bi-Weekly": 26, "Week": 52, "Hour": 2080}
yearly_factor = F.create_map(*[F.lit(x) for kv in YEARLY.items() for x in kv])


def money(col: str):
    return F.regexp_replace(F.col(col), "[$,]", "").cast("double")


def day(col: str):
    return F.to_date(F.substring(F.col(col), 1, 10))


def flag(col: str):
    return F.upper(F.substring(F.col(col), 1, 1)) == F.lit("Y")


raw = (
    spark.read.option("basePath", base)
    .parquet(f"{base}fiscal_year=*/quarter=*/lca_selected.parquet")
    .withColumn("source_file", F.col("_metadata.file_path"))
)

filings = raw.select(
    F.col("case_number"),
    F.col("case_status"),
    F.col("visa_class"),
    day("received_date").alias("received_date"),
    day("decision_date").alias("decision_date"),
    F.col("fiscal_year").cast("int").alias("fiscal_year"),
    F.col("quarter").alias("fiscal_quarter"),
    F.col("employer_name"),
    F.col("trade_name_dba"),
    F.col("employer_city"),
    F.col("employer_state"),
    F.col("naics_code"),
    F.col("job_title"),
    F.regexp_replace("soc_code", r"\.\d+$", "").alias("soc_code"),
    F.col("soc_title"),
    flag("full_time_position").alias("is_full_time"),
    F.col("total_worker_positions").cast("int").alias("worker_positions"),
    day("begin_date").alias("begin_date"),
    day("end_date").alias("end_date"),
    F.col("worksite_city"),
    F.col("worksite_county"),
    F.col("worksite_state"),
    F.col("worksite_postal_code"),
    money("wage_rate_of_pay_from").alias("wage_from"),
    money("wage_rate_of_pay_to").alias("wage_to"),
    F.col("wage_unit_of_pay").alias("wage_unit"),
    (money("wage_rate_of_pay_from") * yearly_factor[F.col("wage_unit_of_pay")]).alias(
        "wage_from_yearly"
    ),
    money("prevailing_wage").alias("prevailing_wage"),
    F.col("pw_unit_of_pay").alias("prevailing_wage_unit"),
    F.col("pw_wage_level").alias("wage_level"),
    flag("h1b_dependent").alias("is_h1b_dependent"),
    flag("willful_violator").alias("is_willful_violator"),
    F.col("source_file"),
)

# A case can sit in more than one file; keep its newest version.
latest = (
    filings.withColumn(
        "rn",
        F.row_number().over(
            Window.partitionBy("case_number").orderBy(
                F.col("decision_date").desc_nulls_last(),
                F.col("fiscal_year").desc(),
                F.col("fiscal_quarter").desc(),
            )
        ),
    )
    .where("rn = 1 AND case_number IS NOT NULL")
    .drop("rn")
)
latest.createOrReplaceTempView("lca_latest")

# COMMAND ----------

spark.sql(f"CREATE TABLE IF NOT EXISTS {silver} AS SELECT * FROM lca_latest WHERE false")
spark.sql(f"COMMENT ON TABLE {silver} IS 'One row per DOL LCA case (H-1B, H-1B1, E-3).'")

result = spark.sql(f"""
MERGE INTO {silver} AS t
USING lca_latest AS s
ON t.case_number = s.case_number
WHEN MATCHED AND (
    s.decision_date > t.decision_date
    OR (t.decision_date IS NULL AND s.decision_date IS NOT NULL)
    OR (s.decision_date <=> t.decision_date AND s.source_file > t.source_file)
  ) THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")
display(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Checks

# COMMAND ----------

checks = {
    "duplicate case_number": f"""
        SELECT count(*) FROM (SELECT case_number FROM {silver} GROUP BY 1 HAVING count(*) > 1)""",
    "rows missing employer, status or decision date": f"""
        SELECT count(*) FROM {silver}
        WHERE employer_name IS NULL OR case_status IS NULL OR decision_date IS NULL""",
}
failed = {}
for name, sql in checks.items():
    n = spark.sql(sql).first()[0]
    print(f"{'OK  ' if n == 0 else 'FAIL'} {name}: {n}")
    if n:
        failed[name] = n
assert not failed, f"Checks failed: {failed}"

# Not a failure, but worth watching: wages that could not be put on a yearly basis.
display(
    spark.sql(f"""
    SELECT fiscal_year, fiscal_quarter,
           count(*)                                         AS cases,
           count_if(case_status = 'Certified')              AS certified,
           count(DISTINCT employer_name)                    AS employers,
           count_if(wage_from_yearly IS NULL)               AS wage_not_yearly,
           percentile_approx(wage_from_yearly, 0.5)         AS median_yearly_wage,
           min(decision_date)                               AS decisions_from,
           max(decision_date)                               AS decisions_to
    FROM {silver}
    GROUP BY ALL
    ORDER BY fiscal_year, fiscal_quarter
    """)
)
