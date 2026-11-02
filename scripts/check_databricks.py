"""Week 1 check: can a Python client on this laptop reach the Databricks SQL warehouse?

Reads DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN from .env.
In the workspace: SQL Warehouses -> your warehouse -> Connection details (hostname, HTTP path);
Settings -> Developer -> Access tokens (personal access token).

If this fails or Free Edition quotas get in the way, the plan's fallback is BigQuery.
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    missing = [
        k
        for k in ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN")
        if not os.getenv(k)
    ]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
        return 2

    from databricks import sql  # optional dependency: pip install -e ".[databricks]"

    t0 = time.monotonic()
    with (
        sql.connect(
            server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("SELECT current_catalog(), current_schema(), current_user(), version()")
        catalog, schema, user, version = cur.fetchone()
        # Can we create and MERGE into a Delta table? That's what weeks 2-3 need.
        cur.execute("CREATE SCHEMA IF NOT EXISTS workspace.jobradar_check")
        cur.execute("CREATE OR REPLACE TABLE workspace.jobradar_check.ping (id INT, seen STRING)")
        cur.execute("""MERGE INTO workspace.jobradar_check.ping t
                       USING (SELECT 1 AS id, 'ok' AS seen) s ON t.id = s.id
                       WHEN NOT MATCHED THEN INSERT *""")
        cur.execute("SELECT count(*) FROM workspace.jobradar_check.ping")
        rows = cur.fetchone()[0]
        cur.execute("DROP SCHEMA workspace.jobradar_check CASCADE")

    print(
        f"OK in {time.monotonic() - t0:.1f}s: user={user} catalog={catalog} schema={schema} "
        f"version={version} merge_rows={rows}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
