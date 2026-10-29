from __future__ import annotations

import sqlite3
from pathlib import Path

from querydoctor.seed import BASE_ROWS, row_counts, seed_database


def dump(path: Path) -> list[tuple[object, ...]]:
    c = sqlite3.connect(path)
    rows = c.execute("SELECT * FROM orders ORDER BY id LIMIT 200").fetchall()
    c.close()
    return rows


def test_row_counts_scale_with_floor() -> None:
    assert row_counts(1.0) == BASE_ROWS
    assert row_counts(0.0001)["users"] == 50


def test_seed_creates_expected_tables_without_extra_indexes(small_db: Path) -> None:
    c = sqlite3.connect(small_db)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "orders" in tables
    for table in tables:
        if table.startswith("sqlite_"):
            continue
        explicit = [r for r in c.execute(f"PRAGMA index_list({table})") if r[3] == "c"]
        assert explicit == [], f"{table} must only have primary-key indexes"
    c.close()


def test_seed_is_deterministic(tmp_path: Path) -> None:
    a, b, other = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    seed_database(a, scale=0.005, seed=1)
    seed_database(b, scale=0.005, seed=1)
    seed_database(other, scale=0.005, seed=2)
    assert dump(a) == dump(b)
    assert dump(a) != dump(other)


def test_seed_reports_progress_and_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    path.write_text("not a database")
    seen: set[str] = set()
    counts = seed_database(path, scale=0.005, progress=lambda t, d, n: seen.add(t))
    assert seen == set(counts)
    c = sqlite3.connect(path)
    assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == counts["users"]
    c.close()


def test_orders_have_a_rare_status_and_skewed_customers(small_db: Path) -> None:
    c = sqlite3.connect(small_db)
    pending, total = c.execute("SELECT SUM(status = 'pending'), COUNT(*) FROM orders").fetchone()
    assert 0.03 < pending / total < 0.15
    low, high = c.execute("SELECT SUM(user_id <= 500), SUM(user_id > 4500) FROM orders").fetchone()
    assert low > high
    c.close()
