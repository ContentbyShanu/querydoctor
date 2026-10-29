"""Shared fixtures. A small seeded database is built once per test session."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from querydoctor.seed import seed_database


@pytest.fixture(scope="session")
def small_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A deterministic database with about 55k rows and only primary-key indexes."""
    path = tmp_path_factory.mktemp("db") / "shop.db"
    seed_database(path, scale=0.05, seed=7)
    return path


@pytest.fixture
def conn(small_db: Path) -> sqlite3.Connection:
    """A read-only connection to the small database."""
    connection = sqlite3.connect(f"{small_db.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    yield connection  # type: ignore[misc]
    connection.close()


@pytest.fixture
def env_paths(tmp_path: Path, small_db: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point every QueryDoctor path setting at temporary locations."""
    paths = {
        "db": small_db,
        "report": tmp_path / "report.json",
        "bench_json": tmp_path / "docs" / "benchmarks.json",
        "bench_md": tmp_path / "docs" / "benchmarks.md",
    }
    monkeypatch.setenv("QUERYDOCTOR_DB", str(paths["db"]))
    monkeypatch.setenv("QUERYDOCTOR_REPORT", str(paths["report"]))
    monkeypatch.setenv("QUERYDOCTOR_BENCH_JSON", str(paths["bench_json"]))
    monkeypatch.setenv("QUERYDOCTOR_BENCH_MD", str(paths["bench_md"]))
    return paths


def schema_signature(path: Path) -> list[tuple[str, str]]:
    """Names and types of every schema object, to prove a database was not modified."""
    c = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return sorted(
            (r[0], r[1])
            for r in c.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        )
    finally:
        c.close()


@pytest.fixture(scope="session")
def sample_report(small_db: Path):  # type: ignore[no-untyped-def]
    """A real analysis report over the small database."""
    from querydoctor.advisor import AdvisorConfig, analyze
    from querydoctor.ingest import parse_queries

    queries = parse_queries(
        "-- name: Orders by user\n"
        "SELECT id, total_cents FROM orders WHERE user_id = 3 ORDER BY created_at DESC LIMIT 20;"
    )
    return analyze(small_db, queries, AdvisorConfig(fast_ms=0.0, max_rounds=2))


@pytest.fixture(scope="session")
def bench_result(small_db: Path):  # type: ignore[no-untyped-def]
    """A real benchmark run over the small database."""
    from querydoctor.bench import run_bench

    return run_bench(small_db)
