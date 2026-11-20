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


# The public web app (CR09 owner view): visitors may not read the owner's Today list or fit
# scores, so their questions run with these limits.
PUBLIC_TABLES = tuple(t for t in GOLD_TABLES if t != "mart_new_postings")
PUBLIC_BLOCKED_COLUMNS = ("fit_score",)


def check(
    sql: str,
    env: str = "prod",
    max_rows: int = MAX_ROWS,
    tables: tuple[str, ...] | None = None,
    blocked_columns: tuple[str, ...] = (),
) -> SafeQuery:
    """tables: the allowed tables (default: all gold tables). blocked_columns: columns the
    query may not read; SELECT * is then refused too, since it would read them."""
    allowed = tables or GOLD_TABLES
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
        if name not in allowed:
            raise SqlRejected(f"table {table.sql()} is not allowed; use only: {', '.join(allowed)}")
        if (table.catalog and table.catalog.lower() != catalog) or (
            table.db and table.db.lower() != db
        ):
            raise SqlRejected(f"use the gold tables in {schema}, not {table.sql()}")
        # Qualify bare names so the query reads the right schema.
        table.set("catalog", exp.to_identifier(catalog))
        table.set("db", exp.to_identifier(db))
        used.add(name)

    if blocked_columns:
        blocked = {c.lower() for c in blocked_columns}
        for col in tree.find_all(exp.Column):
            if col.name.lower() in blocked:
                raise SqlRejected(f"column {col.name} is private and can't be read here")
        if any(not isinstance(star.parent, exp.Count) for star in tree.find_all(exp.Star)):
            raise SqlRejected("list the columns you need instead of SELECT *")

    for func in tree.find_all(exp.Func):
        fname = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if fname.startswith(BLOCKED_FUNCTION_PREFIXES):
            raise SqlRejected(f"function {fname}() is not allowed")

    inner = tree.sql(dialect="databricks")
    return SafeQuery(
        sql=f"SELECT * FROM ({inner}) AS q LIMIT {max_rows}", tables=tuple(sorted(used))
    )
