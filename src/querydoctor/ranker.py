"""Ranking, confidence and plain-English explanations for validated candidates.

score = log2(speedup) / (1 + 0.5 * write_overhead + 2 * size_ratio)

* ``log2(speedup)`` rewards each doubling of speed equally, so a 1000x win does not drown out
  everything else.
* ``write_overhead`` is the relative slowdown of inserts (capped at 4, i.e. +400%).
* ``size_ratio`` is the index size divided by the database size.
"""

from __future__ import annotations

import math
from typing import Literal

from querydoctor.formatting import fmt_bytes, fmt_ms, fmt_percent, fmt_speedup
from querydoctor.models import (
    CandidateOutcome,
    CandidateResult,
    Finding,
    FindingKind,
    Recommendation,
)

WRITE_WEIGHT = 0.5
SIZE_WEIGHT = 2.0
WRITE_CAP = 4.0
HIGH_CONFIDENCE_SPEEDUP = 3.0
MEDIUM_CONFIDENCE_SPEEDUP = 1.5
NOISE_LIMIT = 0.25
EXPENSIVE_WRITE_OVERHEAD = 1.0
EXPENSIVE_WRITE_MIN_SPEEDUP = 3.0
FOLLOW_UP_MIN_SPEEDUP = 1.5

Confidence = Literal["high", "medium", "low"]


def score(speedup: float, write_overhead: float | None, size_bytes: int, db_bytes: int) -> float:
    """Combine benefit and cost into a single comparable number."""
    benefit = math.log2(max(speedup, 1.0))
    write = min(write_overhead or 0.0, WRITE_CAP)
    size_ratio = size_bytes / db_bytes if db_bytes else 0.0
    return benefit / (1.0 + WRITE_WEIGHT * write + SIZE_WEIGHT * size_ratio)


def confidence(result: CandidateResult) -> Confidence:
    """How much to trust a result: size of the win, stability of the timings, same answer."""
    speedup = result.speedup or 0.0
    steady = (result.cv or 0.0) <= NOISE_LIMIT
    if result.results_match and result.used_index and speedup >= HIGH_CONFIDENCE_SPEEDUP and steady:
        return "high"
    if result.results_match and result.used_index and speedup >= MEDIUM_CONFIDENCE_SPEEDUP:
        return "medium"
    return "low"


def _kinds(findings: list[Finding], table: str | None = None) -> set[FindingKind]:
    return {f.kind for f in findings if table is None or f.table in (None, table)}


def explain(result: CandidateResult, findings_before: list[Finding]) -> str:
    """Write a short, plain-English reason why the index helps."""
    cand = result.candidate
    columns = ", ".join(cand.columns)
    before = _kinds(findings_before, cand.table)
    after = _kinds(result.findings_after, cand.table)
    sentences: list[str] = []
    if FindingKind.AUTO_INDEX in before and FindingKind.AUTO_INDEX not in after:
        sentences.append(
            f"SQLite was building a temporary index on {cand.table} for every run; "
            "a permanent index removes that repeated cost."
        )
    elif FindingKind.FULL_SCAN in before and FindingKind.FULL_SCAN not in after:
        sentences.append(
            f"Replaces a full scan of {cand.table} with a direct search on ({columns})."
        )
    else:
        sentences.append(f"Lets SQLite find the needed {cand.table} rows through ({columns}).")
    if FindingKind.TEMP_SORT in before and FindingKind.TEMP_SORT not in after:
        sentences.append("Rows come out already in ORDER BY order, so the temporary sort is gone.")
    if FindingKind.TEMP_GROUP in before and FindingKind.TEMP_GROUP not in after:
        sentences.append("Rows arrive grouped, so no temporary grouping structure is needed.")
    if cand.kind == "covering":
        sentences.append(
            "The index holds every column the query reads, so the table is not touched."
        )
    if cand.kind == "partial" and cand.where:
        sentences.append(f"It only covers rows where {cand.where}, which keeps it small.")
    if cand.kind == "composite":
        sentences.append("Equality columns come first, then the range or ordering column.")
    if result.after_ms is not None and result.speedup is not None:
        sentences.append(
            f"Measured from {fmt_ms(result.baseline_ms)} to {fmt_ms(result.after_ms)} "
            f"({fmt_speedup(result.speedup)} faster)."
        )
    cost = f"Costs {fmt_bytes(result.size_bytes or 0)} of disk"
    if result.write_overhead is not None:
        cost += f" and makes inserts about {fmt_percent(result.write_overhead)} slower"
    sentences.append(cost + ".")
    return " ".join(sentences)


def to_recommendation(
    result: CandidateResult,
    rank: int,
    findings_before: list[Finding],
    db_bytes: int,
) -> Recommendation:
    """Convert a validated result into a ranked recommendation."""
    if result.after_ms is None or result.speedup is None:
        raise ValueError("Only measured results can become recommendations.")
    cand = result.candidate
    return Recommendation(
        rank=rank,
        candidate=cand,
        baseline_ms=result.baseline_ms,
        after_ms=result.after_ms,
        speedup=result.speedup,
        size_bytes=result.size_bytes or 0,
        build_ms=result.build_ms or 0.0,
        write_overhead=result.write_overhead,
        score=round(
            score(result.speedup, result.write_overhead, result.size_bytes or 0, db_bytes), 3
        ),
        confidence=confidence(result),
        explanation=explain(result, findings_before),
        create_sql=cand.create_sql,
        rollback_sql=cand.rollback_sql,
    )


def apply_cost_guard(results: list[CandidateResult], *, follow_up: bool) -> None:
    """Reject candidates whose gain does not justify their cost.

    * An index that more than doubles insert time must earn at least a 3x speedup.
    * Every index after the first for the same query must earn at least 1.5x on top.
    """
    for r in results:
        if r.status != CandidateOutcome.RECOMMENDED or r.speedup is None:
            continue
        costly = (r.write_overhead or 0.0) > EXPENSIVE_WRITE_OVERHEAD
        if costly and r.speedup < EXPENSIVE_WRITE_MIN_SPEEDUP:
            r.status = CandidateOutcome.TOO_SMALL_GAIN
            r.note = "Gain does not justify the write overhead."
        elif follow_up and r.speedup < FOLLOW_UP_MIN_SPEEDUP:
            r.status = CandidateOutcome.TOO_SMALL_GAIN
            r.note = "Marginal gain on top of the first index is too small to justify another."


def pick_best(results: list[CandidateResult], db_bytes: int) -> CandidateResult | None:
    """Return the highest scoring recommended result, or ``None`` if there is none."""
    eligible = [r for r in results if r.status == "recommended" and r.speedup is not None]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda r: score(r.speedup or 1.0, r.write_overhead, r.size_bytes or 0, db_bytes),
    )
