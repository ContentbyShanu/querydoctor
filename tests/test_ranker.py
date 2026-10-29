from __future__ import annotations

import pytest

from querydoctor.models import (
    Candidate,
    CandidateOutcome,
    CandidateResult,
    Finding,
    FindingKind,
    Severity,
)
from querydoctor.ranker import (
    apply_cost_guard,
    confidence,
    explain,
    pick_best,
    score,
    to_recommendation,
)


def result(
    speedup: float = 10.0,
    write: float | None = 0.2,
    size: int = 1_000_000,
    kind: str = "composite",
    status: CandidateOutcome = CandidateOutcome.RECOMMENDED,
    cv: float = 0.05,
    match: bool = True,
    name: str = "idx_a",
    findings_after: list[Finding] | None = None,
) -> CandidateResult:
    return CandidateResult(
        candidate=Candidate(
            table="orders",
            columns=["user_id", "created_at"],
            where="status = 'pending'" if kind == "partial" else None,
            kind=kind,  # type: ignore[arg-type]
            name=name,
            rationale="r",
        ),
        status=status,
        used_index=True,
        baseline_ms=100.0,
        after_ms=100.0 / speedup,
        speedup=speedup,
        build_ms=50.0,
        size_bytes=size,
        write_overhead=write,
        results_match=match,
        cv=cv,
        findings_after=findings_after or [],
    )


def test_score_rewards_speed_and_penalizes_cost() -> None:
    cheap = score(10, 0.1, 1_000, 10_000_000)
    pricey = score(10, 2.0, 5_000_000, 10_000_000)
    faster = score(100, 0.1, 1_000, 10_000_000)
    assert faster > cheap > pricey > 0


def test_score_without_speedup_is_zero() -> None:
    assert score(0.5, None, 0, 0) == 0


@pytest.mark.parametrize(
    ("speedup", "cv", "match", "expected"),
    [
        (10, 0.05, True, "high"),
        (10, 0.6, True, "medium"),
        (2, 0.05, True, "medium"),
        (1.3, 0.05, True, "low"),
        (50, 0.05, False, "low"),
    ],
)
def test_confidence(speedup: float, cv: float, match: bool, expected: str) -> None:
    assert confidence(result(speedup=speedup, cv=cv, match=match)) == expected


def test_explanation_mentions_removed_scan_and_sort() -> None:
    before = [
        Finding(kind=FindingKind.FULL_SCAN, severity=Severity.HIGH, table="orders", message="m"),
        Finding(kind=FindingKind.TEMP_SORT, severity=Severity.MEDIUM, message="m"),
    ]
    text = explain(result(), before)
    assert "full scan of orders" in text
    assert "temporary sort is gone" in text
    assert "Measured from 100 ms to 10 ms" in text
    assert "inserts about 20% slower" in text


def test_explanation_for_partial_and_covering() -> None:
    assert "status = 'pending'" in explain(result(kind="partial"), [])
    assert "table is not touched" in explain(result(kind="covering"), [])


def test_explanation_for_automatic_index() -> None:
    before = [
        Finding(kind=FindingKind.AUTO_INDEX, severity=Severity.HIGH, table="orders", message="m")
    ]
    assert "temporary index" in explain(result(), before)


def test_cost_guard_rejects_expensive_small_wins_and_weak_follow_ups() -> None:
    expensive = result(speedup=2.0, write=1.5)
    weak_follow_up = result(speedup=1.3, write=0.1)
    fine = result(speedup=5.0, write=1.5)
    apply_cost_guard([expensive, fine], follow_up=False)
    assert expensive.status == CandidateOutcome.TOO_SMALL_GAIN
    assert fine.status == CandidateOutcome.RECOMMENDED
    apply_cost_guard([weak_follow_up], follow_up=True)
    assert weak_follow_up.status == CandidateOutcome.TOO_SMALL_GAIN


def test_pick_best_prefers_better_score() -> None:
    cheap = result(speedup=20, write=0.1, size=1_000, name="cheap")
    bloated = result(speedup=20, write=3.0, size=5_000_000, name="bloated")
    best = pick_best([bloated, cheap], 10_000_000)
    assert best is cheap


def test_pick_best_ignores_non_recommended() -> None:
    assert pick_best([result(status=CandidateOutcome.NOT_USED)], 1) is None


def test_to_recommendation_populates_fields() -> None:
    rec = to_recommendation(result(), 1, [], 10_000_000)
    assert rec.rank == 1
    assert rec.create_sql.startswith("CREATE INDEX idx_a")
    assert rec.rollback_sql == "DROP INDEX IF EXISTS idx_a"
    assert rec.score > 0


def test_to_recommendation_requires_measurements() -> None:
    unmeasured = result()
    unmeasured.after_ms = None
    with pytest.raises(ValueError, match="measured"):
        to_recommendation(unmeasured, 1, [], 1)
