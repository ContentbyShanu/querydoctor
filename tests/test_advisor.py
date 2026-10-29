from __future__ import annotations

from pathlib import Path

import pytest

from querydoctor.advisor import AdvisorConfig, SqliteStats, _extends, analyze, describe_schema
from querydoctor.engine import SQLiteEngine, open_readonly
from querydoctor.ingest import QueryInput, parse_queries
from querydoctor.models import Candidate, CandidateOutcome, CandidateResult, FullReport
from querydoctor.sandbox import Sandbox

from .conftest import schema_signature

FORCE = AdvisorConfig(fast_ms=0.0, max_rounds=2)


def run(db: Path, text: str, cfg: AdvisorConfig = FORCE) -> FullReport:
    return analyze(db, parse_queries(text), cfg)


def test_end_to_end_recommendation(sample_report: FullReport) -> None:
    q = sample_report.queries[0]
    assert q.status == "optimized"
    assert q.recommendations
    first = q.recommendations[0]
    assert first.rank == 1
    assert first.speedup > 1.25
    assert first.candidate.table == "orders"
    assert q.final_ms is not None and q.baseline_ms is not None
    assert q.final_ms < q.baseline_ms
    assert q.plan_before and q.plan_after
    assert q.tested
    assert "Orders by user" in sample_report.headline
    assert "CREATE INDEX IF NOT EXISTS" in sample_report.migration_sql
    assert "DROP INDEX IF EXISTS" in sample_report.rollback_sql
    assert {t.name for t in sample_report.tables} >= {"orders", "users"}


def test_summary_and_last_recommendation_agree(sample_report: FullReport) -> None:
    q = sample_report.queries[0]
    assert q.final_ms == q.recommendations[-1].after_ms
    assert q.speedup == pytest.approx((q.baseline_ms or 0) / (q.final_ms or 1))


def test_tested_candidates_are_labelled(sample_report: FullReport) -> None:
    statuses = {t.status for t in sample_report.queries[0].tested}
    assert CandidateOutcome.RECOMMENDED in statuses
    assert all(t.candidate.create_sql for t in sample_report.queries[0].tested)


def test_original_database_is_unchanged(small_db: Path) -> None:
    before = schema_signature(small_db)
    run(small_db, "SELECT id FROM orders WHERE user_id = 5;")
    assert schema_signature(small_db) == before


def test_fast_queries_are_left_alone(small_db: Path) -> None:
    report = run(small_db, "SELECT 1;", AdvisorConfig(fast_ms=1_000.0))
    assert report.queries[0].status == "already_fast"
    assert report.queries[0].recommendations == []
    assert "No index changes" in report.migration_sql


def test_unsafe_sql_becomes_an_error_entry(small_db: Path) -> None:
    report = run(small_db, "DELETE FROM orders;")
    assert report.queries[0].status == "error"
    assert "not allowed" in report.queries[0].message or "Only SELECT" in report.queries[0].message


def test_sql_errors_become_error_entries(small_db: Path) -> None:
    report = run(small_db, "SELECT * FROM does_not_exist;")
    assert report.queries[0].status == "error"
    assert "does_not_exist" in report.queries[0].message


def test_well_indexed_query_reports_no_improvement(small_db: Path) -> None:
    report = run(small_db, "SELECT * FROM orders WHERE id = 5;")
    assert report.queries[0].status == "no_improvement"
    assert report.headline == "No index changes were needed."


def test_progress_callback_receives_each_query(small_db: Path) -> None:
    seen: list[tuple[int, int, str]] = []
    queries = [
        QueryInput(id="a", sql="SELECT 1", title="One"),
        QueryInput(id="b", sql="SELECT 2"),
    ]
    analyze(small_db, queries, FORCE, lambda i, n, label: seen.append((i, n, label)))
    assert seen == [(1, 2, "One"), (2, 2, "b")]


def test_describe_schema(small_db: Path) -> None:
    tables = {t.name: t for t in describe_schema(small_db)}
    assert tables["orders"].rows > 0
    assert tables["orders"].indexes == []


def test_stats_measure_cardinality_and_value_share(small_db: Path) -> None:
    conn = open_readonly(small_db)
    engine = SQLiteEngine(conn)
    counts = {t: engine.row_count(t) for t in engine.tables()}
    stats = SqliteStats(engine, counts, sample=10_000)
    assert stats.distinct_ratio("orders", "status") < 0.01
    assert stats.distinct_ratio("orders", "id") == 1.0
    pending = stats.value_fraction("orders", "status", "'pending'")
    assert pending is not None and 0.03 < pending < 0.15
    assert stats.value_fraction("orders", "status", "'nope'") == 0.0
    assert stats.value_fraction("orders", "status", "'pending'") == pending
    empty = SqliteStats(engine, {"orders": 0}, sample=10)
    assert empty.value_fraction("orders", "status", "'x'") is None
    conn.close()


def test_multiple_rounds_can_add_a_second_index(small_db: Path) -> None:
    sql = (
        "SELECT COUNT(*) FROM users u WHERE u.country = 'SG' AND EXISTS "
        "(SELECT 1 FROM orders o WHERE o.user_id = u.id AND o.status = 'pending')"
    )
    report = run(small_db, sql, AdvisorConfig(fast_ms=0.0, max_rounds=3))
    q = report.queries[0]
    assert q.status == "optimized"
    assert len(q.recommendations) >= 1
    with Sandbox(small_db) as sb:
        assert sb.engine.indexes("orders") == []


def test_composite_replaces_the_prefix_index_it_extends(
    small_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = iter(["idx_orders_user_id", "idx_orders_user_id_created_at"])

    def fake_pick(results: list[CandidateResult], db_bytes: int) -> CandidateResult | None:
        name = next(order, None)
        if name is None:
            return None
        found = [r for r in results if r.candidate.name == name]
        for r in found:
            r.status = CandidateOutcome.RECOMMENDED
        return found[0] if found else None

    monkeypatch.setattr("querydoctor.advisor.pick_best", fake_pick)
    sql = "SELECT id, total_cents FROM orders WHERE user_id = 3 ORDER BY created_at DESC LIMIT 20;"
    q = run(small_db, sql, AdvisorConfig(fast_ms=0.0, max_rounds=3)).queries[0]
    assert [r.candidate.name for r in q.recommendations] == ["idx_orders_user_id_created_at"]
    replaced = next(t for t in q.tested if t.candidate.name == "idx_orders_user_id")
    assert replaced.status == CandidateOutcome.ALTERNATIVE
    assert "Replaced by" in (replaced.note or "")


def test_extends_helper() -> None:
    def c(cols: list[str], where: str | None = None, table: str = "t") -> Candidate:
        return Candidate(
            table=table, columns=cols, where=where, kind="single", name="n", rationale="r"
        )

    assert _extends(c(["a"]), c(["a", "b"]))
    assert not _extends(c(["a", "b"]), c(["a"]))
    assert not _extends(c(["b"]), c(["a", "b"]))
    assert not _extends(c(["a"]), c(["a", "b"], where="x = 1"))
    assert not _extends(c(["a"]), c(["a", "b"], table="u"))
