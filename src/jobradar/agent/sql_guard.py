"""Check every SQL query the assistant writes before it reaches Databricks.

The assistant may only read the gold tables. A query is allowed when it is exactly one
SELECT (or WITH ... SELECT, or UNION of SELECTs) over the approved tables, calls no risky
functions, and gets a row limit. Anything else is refused with a reason the model can read
and correct. This is the main guardrail (CR08); a read-only Databricks identity in M5 is the
second layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

GOLD_TABLES = (
    "dim_employer",
    "fct_postings",
    "fct_lca",
    "mart_new_postings",
    "mart_sponsor_stats",
)
# Functions that read files, call the network or other models, or touch the JVM or secrets.
BLOCKED_FUNCTION_PREFIXES = (
    "read_",
    "ai_",
    "http",
    "reflect",
    "java_method",
    "secret",
    "try_secret",
)
MAX_ROWS = 100


class SqlRejected(ValueError):
    """The query broke a rule; the message says which, so the model can fix it."""


@dataclass(frozen=True)
class SafeQuery:
    sql: str  # what runs: the checked query wrapped in a row limit
    tables: tuple[str, ...]


def gold_schema(env: str = "prod") -> str:
    return f"workspace.{'jobradar_dev' if env == 'dev' else 'jobradar'}_gold"


def check(sql: str, env: str = "prod", max_rows: int = MAX_ROWS) -> SafeQuery:
    schema = gold_schema(env)
    catalog, db = schema.split(".")
    try:
        statements = [s for s in sqlglot.parse(sql, read="databricks") if s is not None]
    except ParseError as e:
        raise SqlRejected(
            f"could not parse the query: {e.errors[0]['description'] if e.errors else e}"
        ) from None
    if len(statements) != 1:
        raise SqlRejected("send exactly one SQL statement (no ';' between statements)")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SqlRejected(f"only SELECT queries are allowed, not {type(tree).__name__.upper()}")
    for node in tree.walk():
        if isinstance(node, (exp.DML, exp.DDL, exp.Command, exp.Set, exp.Use)):
            raise SqlRejected(
                f"{type(node).__name__.upper()} is not allowed; read-only SELECT only"
            )

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlRejected("table functions such as read_files() or range() are not allowed")
        name = table.name.lower()
        if not table.db and name in cte_names:
            continue
        if name not in GOLD_TABLES:
            raise SqlRejected(
                f"table {table.sql()} is not allowed; use only: {', '.join(GOLD_TABLES)}"
            )
        if (table.catalog and table.catalog.lower() != catalog) or (
            table.db and table.db.lower() != db
        ):
            raise SqlRejected(f"use the gold tables in {schema}, not {table.sql()}")
        # Qualify bare names so the query reads the right schema.
        table.set("catalog", exp.to_identifier(catalog))
        table.set("db", exp.to_identifier(db))
        used.add(name)

    for func in tree.find_all(exp.Func):
        fname = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if fname.startswith(BLOCKED_FUNCTION_PREFIXES):
            raise SqlRejected(f"function {fname}() is not allowed")

    inner = tree.sql(dialect="databricks")
    return SafeQuery(
        sql=f"SELECT * FROM ({inner}) AS q LIMIT {max_rows}", tables=tuple(sorted(used))
    )
