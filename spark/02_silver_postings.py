# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: postings
# MAGIC
# MAGIC Turns each board's **latest** raw snapshot from bronze into one row per job posting, and
# MAGIC keeps history with a Delta `MERGE` on `(source, posting_id)`:
# MAGIC
# MAGIC | Case | What happens |
# MAGIC |---|---|
# MAGIC | New posting | Inserted with `first_seen`, `last_seen`, `is_open = true` |
# MAGIC | Posting still on its board | Fields refreshed, `last_seen` moves on; reopened if closed |
# MAGIC | Posting gone from a board whose latest fetch worked | `is_open = false`, `closed_on` set |
# MAGIC
# MAGIC A board whose fetch failed keeps its previous snapshot as "latest", so a failed fetch
# MAGIC never closes postings. `last_seen` comes from the ingest run log, so a board that was
# MAGIC fetched but unchanged (no new file) still counts as seen that day.
# MAGIC
# MAGIC Safe to rerun: a second run on the same data changes nothing.

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "src")))

from pyspark import cloudpickle
from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

import jobradar.lakehouse.postings as postings
from jobradar.lakehouse.paths import schema

# Ship the parser module's code with the UDF, so Spark workers don't need the repo on disk.
cloudpickle.register_pickle_by_value(postings)

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("bucket", "job-radar-ad-4312")
env = dbutils.widgets.get("env")
bucket = dbutils.widgets.get("bucket")

bronze = f"{schema(env, 'bronze')}.job_board_snapshots"
silver = f"{schema(env, 'silver')}.postings"
run_log_path = f"s3://{bucket}/{env}/ops/pipeline_runs/"
print(f"env={env}\nbronze={bronze}\nsilver={silver}\nrun_log={run_log_path}")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {silver} (
  source             STRING  COMMENT 'greenhouse or ashby',
  company            STRING  COMMENT 'company slug from config/companies.yaml',
  posting_id         STRING  COMMENT 'job id on the board; unique within a source',
  title              STRING,
  department         STRING,
  team               STRING,
  location           STRING,
  is_remote          BOOLEAN,
  workplace_type     STRING  COMMENT 'Ashby only: OnSite, Hybrid or Remote',
  employment_type    STRING  COMMENT 'Ashby only: FullTime, PartTime, Intern, Contract',
  url                STRING,
  published_at       STRING  COMMENT 'when the employer first published it, as the board reports',
  source_updated_at  STRING,
  description_text   STRING  COMMENT 'plain text, one line per paragraph or list item',
  salary_min         DOUBLE,
  salary_max         DOUBLE,
  salary_currency    STRING,
  salary_interval    STRING,
  salary_source      STRING  COMMENT 'structured (board field) or description (parsed from text)',
  content_hash       STRING  COMMENT 'bronze snapshot the current values came from',
  first_seen         DATE    COMMENT 'first day Job Radar saw it (not the publish date)',
  last_seen          DATE    COMMENT 'last day it was on a successfully fetched board',
  is_open            BOOLEAN,
  closed_on          DATE    COMMENT 'day Job Radar noticed it was gone; null while open',
  updated_at         TIMESTAMP
)
COMMENT 'One row per job posting ever seen, with first and last seen dates.'
""")

# COMMAND ----------

# 1. Latest snapshot per board.
latest = (
    spark.table(bronze)
    .withColumn(
        "rn",
        F.row_number().over(
            Window.partitionBy("source", "company").orderBy(
                F.col("load_date").desc(), F.col("file_modified").desc()
            )
        ),
    )
    .where("rn = 1")
    .drop("rn")
)

# 2. Last day each board was fetched successfully (landed or unchanged), from the run log.
try:
    last_ok = (
        spark.read.json(run_log_path)
        .where("stage = 'fetch_board' AND status IN ('landed', 'unchanged')")
        .groupBy("source", "company")
        .agg(F.max(F.to_date("load_date")).alias("last_ok_date"))
    )
    _ = last_ok.columns  # resolve now, so a missing path is caught here
except Exception as e:  # no run log yet in this env
    print(f"No run log found ({type(e).__name__}); using snapshot dates only")
    last_ok = spark.createDataFrame([], "source string, company string, last_ok_date date")

boards = latest.join(last_ok, ["source", "company"], "left").withColumn(
    "seen_date", F.greatest("load_date", F.coalesce("last_ok_date", "load_date"))
)

# 3. One row per posting in each board's latest snapshot.
posting_type = T.ArrayType(
    T.StructType(
        [
            T.StructField(
                name,
                T.DoubleType()
                if name in ("salary_min", "salary_max")
                else T.BooleanType()
                if name == "is_remote"
                else T.StringType(),
            )
            for name in postings.POSTING_FIELDS
        ]
    )
)
parse_board = F.udf(postings.parse_board_rows, posting_type)

current = (
    boards.select(
        "source",
        "company",
        "content_hash",
        F.col("load_date").alias("snapshot_date"),
        "seen_date",
        F.explode(parse_board("source", "raw_json")).alias("p"),
    )
    .select("source", "company", "content_hash", "snapshot_date", "seen_date", "p.*")
    .dropDuplicates(["source", "posting_id"])
)
current.createOrReplaceTempView("current_postings")

board_dates = {
    (r["source"], r["company"]): r["seen_date"]
    for r in boards.select("source", "company", "seen_date").collect()
}
print(f"{len(board_dates)} boards, {current.count()} postings in their latest snapshots")

# COMMAND ----------

# 4. MERGE. Only postings of boards that have a snapshot can be closed; closed_on is that
#    board's last successful fetch date.
board_keys = ", ".join(f"'{s}/{c}'" for s, c in board_dates)
closed_on_case = " ".join(
    f"WHEN '{s}/{c}' THEN DATE'{d.isoformat()}'" for (s, c), d in board_dates.items()
)
value_cols = [c for c in postings.POSTING_FIELDS if c != "posting_id"] + ["content_hash"]
set_values = ",\n    ".join(f"t.{c} = s.{c}" for c in value_cols)

merge_sql = f"""
MERGE INTO {silver} AS t
USING current_postings AS s
ON t.source = s.source AND t.posting_id = s.posting_id
WHEN MATCHED THEN UPDATE SET
    {set_values},
    t.company = s.company,
    t.last_seen = greatest(t.last_seen, s.seen_date),
    t.is_open = true,
    t.closed_on = NULL,
    t.updated_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (
    source, company, posting_id, {", ".join(value_cols)},
    first_seen, last_seen, is_open, closed_on, updated_at
) VALUES (
    s.source, s.company, s.posting_id, {", ".join("s." + c for c in value_cols)},
    s.snapshot_date, s.seen_date, true, NULL, current_timestamp()
)
WHEN NOT MATCHED BY SOURCE
    AND t.is_open
    AND concat(t.source, '/', t.company) IN ({board_keys})
THEN UPDATE SET
    t.is_open = false,
    t.closed_on = CASE concat(t.source, '/', t.company) {closed_on_case} END,
    t.updated_at = current_timestamp()
"""
result = spark.sql(merge_sql)
display(result)  # rows inserted, updated (still open or closed) and deleted (always 0)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Checks
# MAGIC The notebook fails here if any check fails.

# COMMAND ----------

checks = {
    "duplicate (source, posting_id)": f"""
        SELECT count(*) FROM (
          SELECT source, posting_id FROM {silver} GROUP BY ALL HAVING count(*) > 1)""",
    "rows missing title, url or first_seen": f"""
        SELECT count(*) FROM {silver}
        WHERE title IS NULL OR url IS NULL OR first_seen IS NULL OR last_seen IS NULL""",
    "last_seen before first_seen": f"SELECT count(*) FROM {silver} WHERE last_seen < first_seen",
    "closed without closed_on, or open with it": f"""
        SELECT count(*) FROM {silver}
        WHERE (NOT is_open AND closed_on IS NULL) OR (is_open AND closed_on IS NOT NULL)""",
    "boards whose open count differs from their latest snapshot": f"""
        SELECT count(*) FROM (
          SELECT c.source, c.company, c.n AS snapshot_jobs, coalesce(o.n, 0) AS open_rows
          FROM (SELECT source, company, count(*) n FROM current_postings GROUP BY ALL) c
          LEFT JOIN (SELECT source, company, count(*) n FROM {silver} WHERE is_open GROUP BY ALL) o
            USING (source, company)
          WHERE c.n != coalesce(o.n, 0))""",
}
failed = {}
for name, sql in checks.items():
    n = spark.sql(sql).first()[0]
    print(f"{'OK  ' if n == 0 else 'FAIL'} {name}: {n}")
    if n:
        failed[name] = n
assert not failed, f"Checks failed: {failed}"

# COMMAND ----------

display(
    spark.sql(f"""
    SELECT source,
           count_if(is_open)                                   AS open_postings,
           count_if(NOT is_open)                               AS closed_postings,
           count(DISTINCT company)                             AS companies,
           round(100 * avg(CAST(salary_min IS NOT NULL AS INT)), 1) AS pct_with_salary,
           min(first_seen)                                     AS first_seen_from,
           max(last_seen)                                      AS last_seen_to
    FROM {silver}
    GROUP BY source
    ORDER BY source
    """)
)
