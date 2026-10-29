from __future__ import annotations

import pytest

from querydoctor.errors import UnsafeSQLError
from querydoctor.safety import split_statements, validate_readonly


def test_accepts_plain_select() -> None:
    assert validate_readonly("SELECT 1;") == "SELECT 1"


def test_accepts_cte_and_union() -> None:
    validate_readonly("WITH a AS (SELECT 1 AS x) SELECT x FROM a")
    validate_readonly("SELECT 1 UNION SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE users SET plan = 'pro'",
        "INSERT INTO users VALUES (1)",
        "DROP TABLE users",
        "CREATE INDEX i ON users (id)",
        "PRAGMA writable_schema = ON",
        "ATTACH DATABASE 'x.db' AS x",
    ],
)
def test_rejects_non_select(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        validate_readonly(sql)


def test_rejects_multiple_statements() -> None:
    with pytest.raises(UnsafeSQLError, match="exactly one"):
        validate_readonly("SELECT 1; DROP TABLE users")


def test_rejects_empty() -> None:
    with pytest.raises(UnsafeSQLError, match="empty"):
        validate_readonly("  ;  ")


def test_rejects_extension_loading() -> None:
    with pytest.raises(UnsafeSQLError, match="not allowed"):
        validate_readonly("SELECT load_extension('evil')")


def test_rejects_unparseable_sql() -> None:
    with pytest.raises(UnsafeSQLError):
        validate_readonly("SELECT FROM WHERE (")


def test_split_statements() -> None:
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_split_statements_rejects_garbage() -> None:
    with pytest.raises(UnsafeSQLError):
        split_statements("SELECT (")
