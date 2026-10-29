"""Read-only SQL validation.

QueryDoctor only ever executes user-supplied SQL after it passes this module, and the
sandbox connection additionally runs with ``PRAGMA query_only = ON`` while doing so.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from querydoctor.errors import UnsafeSQLError

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Merge,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)
_FORBIDDEN_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile"})


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements (without trailing semicolons)."""
    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except ParseError as exc:
        raise UnsafeSQLError(f"Could not parse SQL: {exc}") from exc
    return [stmt.sql(dialect="sqlite") for stmt in parsed if stmt is not None]


def validate_readonly(sql: str) -> str:
    """Return the statement unchanged if it is a single read-only ``SELECT``.

    Raises:
        UnsafeSQLError: if the SQL is empty, has several statements, fails to parse,
            or contains anything other than a read-only query.
    """
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeSQLError("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(text, read="sqlite") if s is not None]
    except ParseError as exc:
        raise UnsafeSQLError(f"Could not parse SQL: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Provide exactly one statement per query.")
    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise UnsafeSQLError("Only SELECT queries can be analyzed.")
    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQLError(f"{type(node).__name__.upper()} is not allowed in a query.")
        if isinstance(node, exp.Anonymous) and node.name.lower() in _FORBIDDEN_FUNCTIONS:
            raise UnsafeSQLError(f"Function {node.name}() is not allowed.")
    return text
