"""The advisor pipeline: analyze, generate candidates, validate in a sandbox, rank."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from querydoctor import __version__
from querydoctor.analyzer import find_problems
from querydoctor.candidates import Stats, generate_candidates
from querydoctor.engine import SQLiteEngine, quote_ident
from querydoctor.errors import QueryDoctorError, QueryTimeoutError
from querydoctor.formatting import fmt_ms, fmt_speedup
from querydoctor.ingest import QueryInput
from querydoctor.migrations import build_migration
from querydoctor.models import (
    Candidate,
    CandidateOutcome,
    CandidateResult,
    FullReport,
    QueryReport,
    TableInfo,
)
from querydoctor.ranker import apply_cost_guard, pick_best, to_recommendation
from querydoctor.safety import validate_readonly
from querydoctor.sandbox import MIN_SPEEDUP, Sandbox

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class AdvisorConfig:
    """Tunable knobs for an analysis run."""

    max_rounds: int = 3
    fast_ms: float = 1.0
    timeout_s: float = 60.0
    write_rows: int = 5000
    sample_rows: int = 50_000


class SqliteStats(Stats):
    """Column statistics measured on the sandbox, cached per column."""

    def __init__(self, engine: SQLiteEngine, row_counts: dict[str, int], sample: int) -> None:
        self.engine = engine
        self.row_counts = row_counts
        self.sample = sample
        self._distinct: dict[tuple[str, str], float] = {}
        self._fraction: dict[tuple[str, str, str], float | None] = {}

    def distinct_ratio(self, table: str, column: str) -> float:
        """Distinct values over a leading sample of the table."""
        key = (table, column)
        if key not in self._distinct:
            t, c = quote_ident(table), quote_ident(column)
            row = self.engine.conn.execute(
                f"SELECT COUNT(DISTINCT {c}), COUNT(*) "
                f"FROM (SELECT {c} FROM {t} LIMIT {self.sample})"
            ).fetchone()
            self._distinct[key] = (row[0] / row[1]) if row and row[1] else 0.0
        return self._distinct[key]

    def value_fraction(self, table: str, column: str, literal: str) -> float | None:
        """Exact fraction of rows equal to a literal taken from the parsed query."""
        key = (table, column, literal)
        if key not in self._fraction:
            total = self.row_counts.get(table, 0)
            if not total:
                self._fraction[key] = None
            else:
                count = self.engine.conn.execute(
                    f"SELECT COUNT(*) FROM {quote_ident(table)} "
                    f"WHERE {quote_ident(column)} = {literal}"
                ).fetchone()[0]
                self._fraction[key] = count / total
        return self._fraction[key]


def _extends(old: Candidate, new: Candidate) -> bool:
    """True if ``new`` strictly extends ``old`` (same table and predicate, ``old`` is a prefix)."""
    return (
        old.table == new.table
        and old.where == new.where
        and len(new.columns) > len(old.columns)
        and new.columns[: len(old.columns)] == old.columns
    )


def _headline(reports: list[QueryReport]) -> str:
    improved = [r for r in reports if r.status == "optimized" and r.speedup]
    if not improved:
        return "No index changes were needed."
    best = max(improved, key=lambda r: r.speedup or 0.0)
    return (
        f"{best.title or best.id}: {fmt_ms(best.baseline_ms or 0)} to "
        f"{fmt_ms(best.final_ms or 0)} ({fmt_speedup(best.speedup or 0)} faster)"
    )


def _advise_query(
    sandbox: Sandbox, item: QueryInput, cfg: AdvisorConfig, db_bytes: int
) -> QueryReport:
    engine = sandbox.engine
    row_counts = sandbox.row_counts()
    report = QueryReport(id=item.id, title=item.title, sql=item.sql, status="error", message="")
    try:
        sql = validate_readonly(item.sql)
        report.sql = sql
        schema = engine.tables()
        pks = {t: engine.primary_key_columns(t) for t in schema}
        stats = SqliteStats(engine, row_counts, cfg.sample_rows)

        report.plan_before = engine.explain(sql)
        report.findings_before = find_problems(report.plan_before, row_counts)
        baseline = engine.measure(sql, timeout_s=cfg.timeout_s)
        report.baseline_ms = baseline.median_ms
        report.rows_returned = baseline.rows
        if baseline.median_ms < cfg.fast_ms:
            report.status = "already_fast"
            report.message = f"Already fast ({fmt_ms(baseline.median_ms)}); nothing to optimize."
            report.final_ms = baseline.median_ms
            report.speedup = 1.0
            report.plan_after = report.plan_before
            report.findings_after = report.findings_before
            return report

        accepted: list[CandidateResult] = []
        current = baseline
        tested: dict[tuple[str, tuple[str, ...], str], CandidateResult] = {}
        for round_no in range(1, cfg.max_rounds + 1):
            existing = {t: engine.indexes(t) for t in schema}
            candidates = generate_candidates(sql, schema, existing, pks, stats)
            if not candidates:
                break
            results = [sandbox.evaluate(c, sql, current, round_no=round_no) for c in candidates]
            apply_cost_guard(results, follow_up=bool(accepted))
            best = pick_best(results, db_bytes)
            for result in results:
                if result is not best and result.status == CandidateOutcome.RECOMMENDED:
                    result.status = CandidateOutcome.ALTERNATIVE
                    result.note = (
                        "Also works, but another index delivers more benefit for less cost."
                    )
                tested.setdefault(result.candidate.signature, result)
            if best is None:
                break
            superseded = next((a for a in accepted if _extends(a.candidate, best.candidate)), None)
            if superseded is not None:
                # The new index starts with the columns of one already accepted, so it makes the
                # earlier one redundant. Re-measure it on its own and keep only the wider index.
                sandbox.drop_index(superseded.candidate)
                accepted.remove(superseded)
                state = engine.measure(sql, timeout_s=cfg.timeout_s)
                fresh = sandbox.evaluate(best.candidate, sql, state, round_no=round_no)
                apply_cost_guard([fresh], follow_up=bool(accepted))
                if fresh.status != CandidateOutcome.RECOMMENDED:
                    sandbox.create_index(superseded.candidate)
                    accepted.append(superseded)
                    break
                superseded.status = CandidateOutcome.ALTERNATIVE
                superseded.note = (
                    f"Replaced by {best.candidate.name}, which starts with the same columns."
                )
                best = fresh
                tested[best.candidate.signature] = fresh
            sandbox.create_index(best.candidate)
            accepted.append(best)
            current = engine.measure(sql, timeout_s=cfg.timeout_s)

        final_ms = current.median_ms
        if accepted:
            # Report the slower of two independent measurements (the evaluation run and the
            # confirmation run after the index was accepted), so the headline is conservative
            # and the recommendation and the query summary always agree.
            last = accepted[-1]
            final_ms = max(last.after_ms or 0.0, current.median_ms)
            last.after_ms = final_ms
            last.speedup = last.baseline_ms / max(final_ms, 0.001)
        report.plan_after = engine.explain(sql)
        report.findings_after = find_problems(report.plan_after, row_counts)
        for result in reversed(accepted):
            sandbox.drop_index(result.candidate)
        winners = {r.candidate.signature for r in accepted}
        for sig, result in tested.items():
            if sig in winners:
                result.status = CandidateOutcome.RECOMMENDED
        report.tested = sorted(
            tested.values(),
            key=lambda r: (r.status != CandidateOutcome.RECOMMENDED, -(r.speedup or 0.0)),
        )
        recommendations = [
            to_recommendation(r, i, report.findings_before, db_bytes)
            for i, r in enumerate(accepted, start=1)
        ]
        report.recommendations = recommendations
        report.final_ms = final_ms
        report.speedup = baseline.median_ms / max(final_ms, 0.001)
        if recommendations:
            report.status = "optimized"
            report.message = (
                f"{len(recommendations)} index{'es' if len(recommendations) > 1 else ''} "
                f"recommended: {fmt_ms(baseline.median_ms)} to {fmt_ms(final_ms)}."
            )
        else:
            report.status = "no_improvement"
            report.message = (
                f"No candidate reached the {MIN_SPEEDUP}x threshold; "
                "the existing indexes are already a good fit."
            )
    except (QueryDoctorError, sqlite3.Error, QueryTimeoutError) as exc:
        report.status = "error"
        report.message = str(exc)
    return report


def analyze(
    db_path: Path,
    queries: list[QueryInput],
    cfg: AdvisorConfig | None = None,
    progress: ProgressCallback | None = None,
) -> FullReport:
    """Analyze ``queries`` against ``db_path`` and return a complete report."""
    cfg = cfg or AdvisorConfig()
    started = time.perf_counter()
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    with Sandbox(db_path, timeout_s=cfg.timeout_s, write_rows=cfg.write_rows) as sandbox:
        reports: list[QueryReport] = []
        for i, item in enumerate(queries, start=1):
            if progress:
                progress(i, len(queries), item.title or item.id)
            reports.append(_advise_query(sandbox, item, cfg, db_bytes))
        engine = sandbox.engine
        tables = [
            TableInfo(
                name=name,
                rows=sandbox.row_counts().get(name, 0),
                columns=cols,
                indexes=[str(ix["name"]) for ix in engine.indexes(name)],
            )
            for name, cols in engine.tables().items()
        ]
    up, down = build_migration(reports)
    measured = [r for r in reports if r.baseline_ms is not None]
    return FullReport(
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        sqlite_version=sqlite3.sqlite_version,
        database=str(db_path),
        database_bytes=db_bytes,
        duration_s=round(time.perf_counter() - started, 2),
        tables=tables,
        queries=reports,
        total_baseline_ms=sum(r.baseline_ms or 0.0 for r in measured),
        total_final_ms=sum(r.final_ms or 0.0 for r in measured),
        headline=_headline(reports),
        migration_sql=up,
        rollback_sql=down,
    )


def describe_schema(db_path: Path) -> list[TableInfo]:
    """Describe the tables of a database without copying it."""
    from querydoctor.engine import open_readonly  # local import keeps module graph simple

    conn = open_readonly(db_path)
    try:
        engine = SQLiteEngine(conn)
        return [
            TableInfo(
                name=name,
                rows=engine.row_count(name),
                columns=cols,
                indexes=[str(ix["name"]) for ix in engine.indexes(name)],
            )
            for name, cols in engine.tables().items()
        ]
    finally:
        conn.close()
