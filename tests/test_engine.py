from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from querydoctor.engine import SQLiteEngine, open_readonly, quote_ident, result_digest
from querydoctor.errors import DatabaseNotFoundError, QueryTimeoutError


def test_tables_and_primary_keys(conn: sqlite3.Connection) -> None:
    engine = SQLiteEngine(conn)
    tables = engine.tables()
    assert set(tables) == {"users", "products", "orders", "order_items", "reviews"}
    assert "user_id" in tables["orders"]
    assert engine.primary_key_columns("orders") == ["id"]
    assert engine.row_count("products") > 0
    assert engine.used_bytes() > 0


def test_explain_reports_tree_depth(conn: sqlite3.Connection) -> None:
    plan = SQLiteEngine(conn).explain(
        "SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)"
    )
    assert plan[0].depth == 0
    assert max(node.depth for node in plan) >= 1


def test_measure_returns_stable_summary(conn: sqlite3.Connection) -> None:
    m = SQLiteEngine(conn).measure("SELECT COUNT(*) FROM orders", timeout_s=10)
    assert m.rows == 1
    assert m.runs in (3, 5, 7)
    assert 0 < m.min_ms <= m.median_ms <= m.max_ms
    assert len(m.digest) == 16


def test_measure_times_out(conn: sqlite3.Connection) -> None:
    sql = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 500000000) "
        "SELECT COUNT(*) FROM c"
    )
    with pytest.raises(QueryTimeoutError):
        SQLiteEngine(conn).measure(sql, timeout_s=0.2)


def test_sql_errors_are_not_swallowed(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        SQLiteEngine(conn).measure("SELECT * FROM missing_table", timeout_s=5)


def test_digest_ignores_order_and_detects_changes() -> None:
    assert result_digest([(1,), (2,)]) == result_digest([(2,), (1,)])
    assert result_digest([(1,)]) != result_digest([(2,)])
    assert result_digest([(i,) for i in range(60_000)]).startswith("count:")


def test_open_readonly_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DatabaseNotFoundError, match="querydoctor seed"):
        open_readonly(tmp_path / "nope.db")


def test_open_readonly_blocks_writes(small_db: Path) -> None:
    c = open_readonly(small_db)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM users")
    c.close()


def test_indexes_include_partial_predicate(tmp_path: Path) -> None:
    c = sqlite3.connect(tmp_path / "x.db")
    c.executescript(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, a INT, b TEXT);"
        "CREATE INDEX i1 ON t (a);"
        "CREATE INDEX i2 ON t (a) WHERE b = 'x';"
    )
    found = {i["name"]: i for i in SQLiteEngine(c).indexes("t")}
    assert found["i1"]["where"] is None
    assert found["i2"]["where"] == "b = 'x'"
    assert found["i2"]["columns"] == ["a"]
    c.close()


def test_quote_ident_escapes_quotes() -> None:
    assert quote_ident('we"ird') == '"we""ird"'
