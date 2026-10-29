from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from querydoctor.models import Candidate, CandidateOutcome
from querydoctor.sandbox import Sandbox

from .conftest import schema_signature

SQL = "SELECT id, total_cents FROM orders WHERE user_id = 3"


def cand(columns: list[str], name: str, where: str | None = None) -> Candidate:
    return Candidate(
        table="orders", columns=columns, where=where, kind="single", name=name, rationale="t"
    )


def test_sandbox_never_touches_the_original(small_db: Path) -> None:
    before = schema_signature(small_db)
    with Sandbox(small_db) as sb:
        base = sb.engine.measure(SQL)
        sb.evaluate(cand(["user_id"], "idx_t_user"), SQL, base)
        sandbox_path = sb.path
    assert schema_signature(small_db) == before
    assert not sandbox_path.exists()


def test_evaluate_measures_and_drops_the_index(small_db: Path) -> None:
    with Sandbox(small_db) as sb:
        base = sb.engine.measure(SQL)
        result = sb.evaluate(cand(["user_id"], "idx_t_user"), SQL, base)
        assert result.used_index
        assert result.results_match
        assert result.speedup and result.speedup > 1.5
        assert result.size_bytes and result.size_bytes > 0
        assert result.build_ms and result.build_ms > 0
        assert result.write_overhead is not None
        assert result.status in (CandidateOutcome.RECOMMENDED, CandidateOutcome.TOO_SMALL_GAIN)
        assert [i["name"] for i in sb.engine.indexes("orders")] == []


def test_unused_index_is_flagged(small_db: Path) -> None:
    with Sandbox(small_db) as sb:
        result = sb.evaluate(cand(["country"], "idx_t_country"), SQL, sb.engine.measure(SQL))
        assert result.status == CandidateOutcome.NOT_USED
        assert not result.used_index
        assert result.note


def test_bad_candidate_reports_error(small_db: Path) -> None:
    with Sandbox(small_db) as sb:
        result = sb.evaluate(cand(["no_such_col"], "idx_t_bad"), SQL, sb.engine.measure(SQL))
        assert result.status == CandidateOutcome.ERROR
        assert result.note
        assert sb.engine.indexes("orders") == []


def test_user_queries_cannot_write(small_db: Path) -> None:
    with Sandbox(small_db) as sb, pytest.raises(sqlite3.OperationalError):
        sb.conn.execute("DELETE FROM orders")


def test_measure_write_rolls_back(small_db: Path) -> None:
    with Sandbox(small_db, write_rows=500) as sb:
        before = sb.engine.row_count("orders")
        elapsed = sb.measure_write("orders")
        assert elapsed is not None and elapsed > 0
        assert sb.engine.row_count("orders") == before


def test_measure_write_gives_up_on_unique_conflicts(tmp_path: Path) -> None:
    path = tmp_path / "w.db"
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b)) WITHOUT ROWID;"
        "INSERT INTO t VALUES (1, 1), (2, 2);"
        "CREATE TABLE empty (id INTEGER PRIMARY KEY, v INT);"
    )
    c.commit()
    c.close()
    with Sandbox(path) as sb:
        assert sb.measure_write("t") is None
        assert sb.measure_write("empty") is None
        assert sb.row_counts() == {"t": 2, "empty": 0}


def test_missing_database_fails_fast(tmp_path: Path) -> None:
    from querydoctor.errors import DatabaseNotFoundError

    with pytest.raises(DatabaseNotFoundError):
        Sandbox(tmp_path / "missing.db")
