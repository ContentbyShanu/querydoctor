"""Sandbox validation.

Candidates are never created on the user's database. The sandbox works on a private copy made
with SQLite's online backup API, runs user SQL with ``PRAGMA query_only = ON`` and drops every
index it creates.
"""

from __future__ import annotations

import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from types import TracebackType

from querydoctor.analyzer import find_problems, plan_uses_index
from querydoctor.engine import SQLiteEngine, open_readonly, quote_ident, writable
from querydoctor.errors import QueryTimeoutError
from querydoctor.models import (
    Candidate,
    CandidateOutcome,
    CandidateResult,
    Measurement,
)

MIN_SPEEDUP = 1.25
WRITE_RUNS = 3


class Sandbox:
    """A throwaway copy of a database where candidate indexes can be tried safely."""

    def __init__(self, source: Path, *, timeout_s: float = 60.0, write_rows: int = 5000) -> None:
        self.source = source
        self.timeout_s = timeout_s
        self.write_rows = write_rows
        self._tmp = tempfile.TemporaryDirectory(prefix="querydoctor-")
        self.path = Path(self._tmp.name) / "sandbox.db"
        origin = open_readonly(source)
        try:
            self.conn = sqlite3.connect(self.path)
            origin.backup(self.conn)
        finally:
            origin.close()
        self.conn.execute("PRAGMA cache_size = -65536")
        self.conn.execute("ANALYZE")
        self.conn.commit()
        self.conn.execute("PRAGMA query_only = ON")
        self.engine = SQLiteEngine(self.conn)
        self._row_counts: dict[str, int] = {}

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection and delete the sandbox copy."""
        self.conn.close()
        self._tmp.cleanup()

    # -- schema helpers -------------------------------------------------------------------

    def row_counts(self) -> dict[str, int]:
        """Row count per table (cached)."""
        if not self._row_counts:
            self._row_counts = {t: self.engine.row_count(t) for t in self.engine.tables()}
        return self._row_counts

    # -- index management -----------------------------------------------------------------

    def create_index(self, candidate: Candidate) -> float:
        """Create the candidate index in the sandbox and return the build time in ms."""
        start = time.perf_counter()
        with writable(self.conn):
            self.conn.execute(candidate.create_sql)
            self.conn.execute(f"ANALYZE {quote_ident(candidate.name)}")
            self.conn.commit()
        return (time.perf_counter() - start) * 1000.0

    def drop_index(self, candidate: Candidate) -> None:
        """Drop a candidate index from the sandbox."""
        with writable(self.conn):
            self.conn.execute(candidate.rollback_sql)
            self.conn.commit()

    # -- write overhead -------------------------------------------------------------------

    def measure_write(self, table: str) -> float | None:
        """Median time (ms) to insert a batch of rows into ``table``, then roll it back."""
        info = self.engine.table_info(table)
        pk = [c for c in info if c["pk"]]
        rowid_alias = pk[0]["name"] if len(pk) == 1 and pk[0]["type"].upper() == "INTEGER" else None
        columns = ", ".join(quote_ident(c["name"]) for c in info)
        values = ", ".join(
            "NULL" if c["name"] == rowid_alias else quote_ident(c["name"]) for c in info
        )
        batch = min(self.write_rows, self.row_counts().get(table, 0))
        if batch == 0:
            return None
        sql = (
            f"INSERT INTO {quote_ident(table)} ({columns}) "
            f"SELECT {values} FROM {quote_ident(table)} LIMIT {batch}"
        )
        samples: list[float] = []
        with writable(self.conn):
            for _ in range(WRITE_RUNS):
                self.conn.execute("BEGIN")
                try:
                    start = time.perf_counter()
                    self.conn.execute(sql)
                    samples.append((time.perf_counter() - start) * 1000.0)
                except sqlite3.IntegrityError:
                    return None
                finally:
                    self.conn.execute("ROLLBACK")
        return statistics.median(samples)

    # -- validation -----------------------------------------------------------------------

    def evaluate(
        self,
        candidate: Candidate,
        sql: str,
        baseline: Measurement,
        *,
        round_no: int = 1,
    ) -> CandidateResult:
        """Create ``candidate``, measure ``sql`` with it, then drop it again."""
        result = CandidateResult(
            candidate=candidate,
            round=round_no,
            status=CandidateOutcome.ERROR,
            used_index=False,
            baseline_ms=baseline.median_ms,
        )
        created = False
        try:
            used_before = self.engine.used_bytes()
            write_without = self.measure_write(candidate.table)
            result.build_ms = self.create_index(candidate)
            created = True
            result.plan_after = self.engine.explain(sql)
            result.findings_after = find_problems(result.plan_after, self.row_counts())
            result.used_index = plan_uses_index(result.plan_after, candidate.name)
            result.size_bytes = max(0, self.engine.used_bytes() - used_before)
            if not result.used_index:
                result.status = CandidateOutcome.NOT_USED
                result.note = "The query planner ignored this index."
                return result
            write_with = self.measure_write(candidate.table)
            if write_without and write_with:
                result.write_overhead = max(0.0, (write_with - write_without) / write_without)
            measured = self.engine.measure(sql, timeout_s=self.timeout_s)
            result.after_ms = measured.median_ms
            result.cv = measured.cv
            result.speedup = baseline.median_ms / max(measured.median_ms, 0.001)
            result.results_match = measured.digest == baseline.digest
            if not result.results_match:
                result.status = CandidateOutcome.RESULT_MISMATCH
                result.note = "Results differed from the baseline, so this index is rejected."
            elif result.speedup < MIN_SPEEDUP:
                result.status = CandidateOutcome.TOO_SMALL_GAIN
                result.note = f"Gain below the {MIN_SPEEDUP}x threshold."
            else:
                result.status = CandidateOutcome.RECOMMENDED
        except (sqlite3.Error, QueryTimeoutError) as exc:
            result.status = CandidateOutcome.ERROR
            result.note = str(exc)
        finally:
            if created:
                self.drop_index(candidate)
        return result
