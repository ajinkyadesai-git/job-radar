# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze: job board snapshots
# MAGIC
# MAGIC Loads every raw board response that `jobradar ingest` landed in S3 into
# MAGIC `<env>_bronze.job_board_snapshots`: **one row per file**, with the JSON kept as a string,
# MAGIC unchanged.
# MAGIC
# MAGIC - **Incremental:** Auto Loader remembers which files it has loaded (in a checkpoint), so a
# MAGIC   rerun loads only new files and loads nothing twice.
# MAGIC - **Read-only on S3:** Databricks reads the bucket through the read-only external location
# MAGIC   `job_radar_bucket`; the checkpoint lives in a Databricks-managed volume.
# MAGIC - **Batch, not streaming:** `availableNow` processes what is there, then stops.
# MAGIC
# MAGIC Parameters: `env` (dev or prod) and `bucket`.

# COMMAND ----------

import os
import sys

# The repo's Python package lives in ../src; add it so the path rules are shared with the ingest.
sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "src")))

from pyspark.sql import functions as F

from jobradar.lakehouse.paths import RAW_BOARD_FILE_PATTERN, raw_board_glob, schema

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("bucket", "job-radar-ad-4312")
env = dbutils.widgets.get("env")
bucket = dbutils.widgets.get("bucket")

bronze = schema(env, "bronze")
table = f"{bronze}.job_board_snapshots"
source_glob = raw_board_glob(bucket, env)
checkpoint = f"/Volumes/{bronze.replace('.', '/')}/_checkpoints/job_board_snapshots"
print(f"env={env}\nsource={source_glob}\ntable={table}\ncheckpoint={checkpoint}")

# COMMAND ----------

# Schemas for every layer, and a volume for Auto Loader's checkpoint. Safe to rerun.
for layer in ("bronze", "silver", "gold", "ops"):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema(env, layer)}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {bronze}._checkpoints")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {table} (
  source         STRING    COMMENT 'greenhouse or ashby',
  company        STRING    COMMENT 'company slug from config/companies.yaml',
  load_date      DATE      COMMENT 'date the ingest landed the file',
  content_hash   STRING    COMMENT 'first 16 hex chars of the SHA-256 of the canonical JSON',
  raw_json       STRING    COMMENT 'board response exactly as landed',
  file_path      STRING    COMMENT 'S3 path of the raw file',
  file_modified  TIMESTAMP COMMENT 'when the file was written to S3',
  loaded_at      TIMESTAMP COMMENT 'when this job loaded the row'
)
COMMENT 'One row per raw job board response landed by jobradar ingest.'
""")

# COMMAND ----------

path = F.col("_metadata.file_path")

snapshots = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "text")
    .option("wholeText", "true")  # one row per file, not per line
    .load(source_glob)
    .select(
        F.regexp_extract(path, RAW_BOARD_FILE_PATTERN, 1).alias("source"),
        F.regexp_extract(path, RAW_BOARD_FILE_PATTERN, 2).alias("company"),
        F.to_date(F.regexp_extract(path, RAW_BOARD_FILE_PATTERN, 3)).alias("load_date"),
        F.regexp_extract(path, RAW_BOARD_FILE_PATTERN, 4).alias("content_hash"),
        F.col("value").alias("raw_json"),
        path.alias("file_path"),
        F.col("_metadata.file_modification_time").alias("file_modified"),
        F.current_timestamp().alias("loaded_at"),
    )
)

query = (
    snapshots.writeStream.option("checkpointLocation", checkpoint)
    .trigger(availableNow=True)
    .toTable(table)
)
query.awaitTermination()
loaded = sum(p["numInputRows"] for p in query.recentProgress)
print(f"Loaded {loaded} new files into {table}")

# COMMAND ----------

# Checks: every row parsed from its path, and each file loaded exactly once.
bad_paths = spark.table(table).where("source = '' OR company = '' OR load_date IS NULL").count()
dupes = spark.sql(f"SELECT file_path FROM {table} GROUP BY file_path HAVING count(*) > 1").count()
assert bad_paths == 0, f"{bad_paths} rows have a path that did not parse"
assert dupes == 0, f"{dupes} files were loaded more than once"

display(
    spark.sql(f"""
    SELECT load_date, source, count(*) AS files, round(sum(length(raw_json)) / 1e6, 1) AS mb
    FROM {table}
    GROUP BY load_date, source
    ORDER BY load_date DESC, source
    """)
)
