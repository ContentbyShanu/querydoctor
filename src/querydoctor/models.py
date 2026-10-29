"""Pydantic models describing candidates, measurements and reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """How much a plan finding is likely to hurt."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingKind(StrEnum):
    """Categories of problems detected in a query plan."""

    FULL_SCAN = "full_scan"
    TEMP_SORT = "temp_sort"
    TEMP_GROUP = "temp_group"
    AUTO_INDEX = "auto_index"
    JOIN_WITHOUT_INDEX = "join_without_index"


class PlanNode(BaseModel):
    """One row of ``EXPLAIN QUERY PLAN`` with its depth in the tree."""

    id: int
    parent: int
    depth: int
    detail: str


class Finding(BaseModel):
    """A problem found in a plan."""

    kind: FindingKind
    severity: Severity
    table: str | None = None
    message: str


class Measurement(BaseModel):
    """Timing summary of repeated executions of one query."""

    median_ms: float
    min_ms: float
    max_ms: float
    cv: float = Field(description="Coefficient of variation (stdev / mean) across runs.")
    runs: int
    rows: int
    digest: str = Field(description="Order-insensitive digest of the result set.")


class Candidate(BaseModel):
    """A proposed index."""

    table: str
    columns: list[str]
    where: str | None = None
    kind: Literal["single", "composite", "covering", "partial"]
    name: str
    rationale: str

    @property
    def create_sql(self) -> str:
        """``CREATE INDEX`` statement for this candidate."""
        cols = ", ".join(self.columns)
        sql = f"CREATE INDEX {self.name} ON {self.table} ({cols})"
        return f"{sql} WHERE {self.where}" if self.where else sql

    @property
    def rollback_sql(self) -> str:
        """``DROP INDEX`` statement that undoes the candidate."""
        return f"DROP INDEX IF EXISTS {self.name}"

    @property
    def signature(self) -> tuple[str, tuple[str, ...], str]:
        """Identity used for de-duplication."""
        return (self.table, tuple(self.columns), self.where or "")


class CandidateOutcome(StrEnum):
    """Outcome of validating one candidate."""

    RECOMMENDED = "recommended"
    ALTERNATIVE = "alternative"
    NOT_USED = "not_used"
    TOO_SMALL_GAIN = "too_small_gain"
    RESULT_MISMATCH = "result_mismatch"
    ERROR = "error"


class CandidateResult(BaseModel):
    """Everything measured about one candidate in the sandbox."""

    candidate: Candidate
    status: CandidateOutcome
    round: int = 1
    used_index: bool
    baseline_ms: float
    after_ms: float | None = None
    speedup: float | None = None
    build_ms: float | None = None
    size_bytes: int | None = None
    write_overhead: float | None = Field(
        default=None, description="Relative slowdown of inserts, 0.25 means +25%."
    )
    results_match: bool | None = None
    cv: float | None = None
    plan_after: list[PlanNode] = Field(default_factory=list)
    findings_after: list[Finding] = Field(default_factory=list)
    note: str | None = None


class Recommendation(BaseModel):
    """A validated index recommendation."""

    rank: int
    candidate: Candidate
    baseline_ms: float
    after_ms: float
    speedup: float
    size_bytes: int
    build_ms: float
    write_overhead: float | None
    score: float
    confidence: Literal["high", "medium", "low"]
    explanation: str
    create_sql: str
    rollback_sql: str


class QueryReport(BaseModel):
    """Result of analyzing a single query."""

    id: str
    title: str | None = None
    sql: str
    status: Literal["optimized", "already_fast", "no_improvement", "error"]
    message: str
    baseline_ms: float | None = None
    final_ms: float | None = None
    speedup: float | None = None
    rows_returned: int | None = None
    plan_before: list[PlanNode] = Field(default_factory=list)
    plan_after: list[PlanNode] = Field(default_factory=list)
    findings_before: list[Finding] = Field(default_factory=list)
    findings_after: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    tested: list[CandidateResult] = Field(default_factory=list)


class TableInfo(BaseModel):
    """Schema summary for one table."""

    name: str
    rows: int
    columns: list[str]
    indexes: list[str]


class FullReport(BaseModel):
    """Result of analyzing a batch of queries."""

    version: str
    generated_at: str
    sqlite_version: str
    database: str
    database_bytes: int
    duration_s: float
    tables: list[TableInfo]
    queries: list[QueryReport]
    total_baseline_ms: float
    total_final_ms: float
    headline: str
    migration_sql: str
    rollback_sql: str
