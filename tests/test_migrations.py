from __future__ import annotations

from querydoctor.migrations import build_migration, unique_recommendations
from querydoctor.models import Candidate, QueryReport, Recommendation


def rec(name: str, speedup: float) -> Recommendation:
    cand = Candidate(table="orders", columns=["user_id"], kind="single", name=name, rationale="r")
    return Recommendation(
        rank=1,
        candidate=cand,
        baseline_ms=100,
        after_ms=100 / speedup,
        speedup=speedup,
        size_bytes=2048,
        build_ms=5,
        write_overhead=0.1,
        score=1.0,
        confidence="high",
        explanation="e",
        create_sql=cand.create_sql,
        rollback_sql=cand.rollback_sql,
    )


def report(title: str, *recs: Recommendation) -> QueryReport:
    return QueryReport(
        id=title,
        title=title,
        sql="SELECT 1",
        status="optimized",
        message="m",
        recommendations=list(recs),
    )


def test_duplicate_indexes_are_merged_and_keep_the_best_numbers() -> None:
    merged = unique_recommendations([report("A", rec("idx_x", 5)), report("B", rec("idx_x", 9))])
    assert len(merged) == 1
    best, labels = merged[0]
    assert best.speedup == 9
    assert labels == ["A", "B"]


def test_migration_and_rollback_scripts() -> None:
    up, down = build_migration([report("A", rec("idx_x", 5)), report("B", rec("idx_y", 3))])
    assert up.count("CREATE INDEX IF NOT EXISTS") == 2
    assert "-- A: 100 ms to 20 ms (5.0x)" in up
    assert down.count("DROP INDEX IF EXISTS") == 2
    assert up.endswith("\n")


def test_empty_migration_says_so() -> None:
    up, down = build_migration([])
    assert "No index changes recommended" in up
    assert "DROP" not in down
