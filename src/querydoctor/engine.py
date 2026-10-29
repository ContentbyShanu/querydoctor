"""Database engine layer.

Everything database specific lives behind :class:`Engine`, so adding PostgreSQL later means
writing one more implementation rather than touching the advisor logic.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from querydoctor.errors import DatabaseNotFoundError, QueryTimeoutError
from querydoctor.models import Measurement, PlanNode

_DIGEST_ROW_LIMIT = 50_000


class Engine(Protocol):
    """Operations the advisor needs from a database."""

    def tables(self) -> dict[str, list[str]]:
        """Map table name to its column names."""

    def explain(self, sql: str) -> list[PlanNode]:
        """Return the query plan for ``sql``."""

    def measure(self, sql: str, *, timeout_s: float) -> Measurement:
        """Execute ``sql`` repeatedly and summarize the timings."""


def quote_ident(name: str) -> str:
    """Quote an identifier for safe use in generated SQL."""
    return '"' + name.replace('"', '""') + '"'


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open a database file read-only, raising a friendly error if it is missing."""
    if not path.exists():
        raise DatabaseNotFoundError(
            f"Database not found: {path}. Run `querydoctor seed` first or pass --db."
        )
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class SQLiteEngine:
    """SQLite implementation of :class:`Engine` over an existing connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # -- schema ---------------------------------------------------------------------------

    def tables(self) -> dict[str, list[str]]:
        """Map each user table to its column names."""
        names = [
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        return {n: [c["name"] for c in self.table_info(n)] for n in names}

    def table_info(self, table: str) -> list[sqlite3.Row]:
        """Rows of ``PRAGMA table_info`` for ``table``."""
        return list(self.conn.execute(f"PRAGMA table_info({quote_ident(table)})"))

    def row_count(self, table: str) -> int:
        """Exact row count of ``table``."""
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])

    def indexes(self, table: str) -> list[dict[str, object]]:
        """Existing indexes of ``table`` with their columns and partial predicate."""
        result: list[dict[str, object]] = []
        for row in self.conn.execute(f"PRAGMA index_list({quote_ident(table)})"):
            name = row["name"]
            cols = [
                r["name"]
                for r in self.conn.execute(f"PRAGMA index_info({quote_ident(name)})")
                if r["name"] is not None
            ]
            master = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
            ).fetchone()
            where = None
            if master and master["sql"]:
                match = re.search(r"\bWHERE\b(.*)$", master["sql"], re.IGNORECASE | re.DOTALL)
                where = match.group(1).strip() if match else None
            result.append(
                {
                    "name": name,
                    "columns": cols,
                    "unique": bool(row["unique"]),
                    "where": where,
                    "origin": row["origin"],
                }
            )
        return result

    def primary_key_columns(self, table: str) -> list[str]:
        """Primary key columns in key order."""
        info = [c for c in self.table_info(table) if c["pk"]]
        return [c["name"] for c in sorted(info, key=lambda c: c["pk"])]

    def used_bytes(self) -> int:
        """Bytes in pages that currently hold data (free pages excluded)."""
        page_size = int(self.conn.execute("PRAGMA page_size").fetchone()[0])
        pages = int(self.conn.execute("PRAGMA page_count").fetchone()[0])
        free = int(self.conn.execute("PRAGMA freelist_count").fetchone()[0])
        return (pages - free) * page_size

    # -- planning -------------------------------------------------------------------------

    def explain(self, sql: str) -> list[PlanNode]:
        """Return ``EXPLAIN QUERY PLAN`` rows with computed depths."""
        rows = self.conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        depth: dict[int, int] = {0: -1}
        nodes: list[PlanNode] = []
        for row in rows:
            node_id, parent, detail = int(row[0]), int(row[1]), str(row[3])
            depth[node_id] = depth.get(parent, -1) + 1
            nodes.append(PlanNode(id=node_id, parent=parent, depth=depth[node_id], detail=detail))
        return nodes

    # -- measuring ------------------------------------------------------------------------

    def _run_once(self, sql: str, deadline: float) -> tuple[float, list[tuple[object, ...]]]:
        def abort() -> int:
            return 1 if time.perf_counter() > deadline else 0

        self.conn.set_progress_handler(abort, 10_000)
        start = time.perf_counter()
        try:
            rows = [tuple(r) for r in self.conn.execute(sql).fetchall()]
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise QueryTimeoutError("Query exceeded the time limit.") from exc
            raise
        finally:
            self.conn.set_progress_handler(None, 0)
        return (time.perf_counter() - start) * 1000.0, rows

    def measure(self, sql: str, *, timeout_s: float = 60.0) -> Measurement:
        """Warm up once, then time several runs and report the median."""
        deadline = time.perf_counter() + timeout_s
        first_ms, rows = self._run_once(sql, deadline)
        runs = 7 if first_ms < 50 else 5 if first_ms < 500 else 3
        samples = []
        for _ in range(runs):
            elapsed, rows = self._run_once(sql, time.perf_counter() + timeout_s)
            samples.append(elapsed)
        mean = statistics.fmean(samples)
        cv = statistics.pstdev(samples) / mean if mean > 0 else 0.0
        return Measurement(
            median_ms=statistics.median(samples),
            min_ms=min(samples),
            max_ms=max(samples),
            cv=cv,
            runs=runs,
            rows=len(rows),
            digest=result_digest(rows),
        )


def result_digest(rows: list[tuple[object, ...]]) -> str:
    """Order-insensitive digest of a result set, used to prove an index changed no results."""
    if len(rows) > _DIGEST_ROW_LIMIT:
        return f"count:{len(rows)}"
    hasher = hashlib.sha256()
    for line in sorted(repr(r) for r in rows):
        hasher.update(line.encode())
    return hasher.hexdigest()[:16]


@contextmanager
def writable(conn: sqlite3.Connection) -> Iterator[None]:
    """Temporarily allow writes on a connection that normally runs ``query_only``."""
    conn.execute("PRAGMA query_only = OFF")
    try:
        yield
    finally:
        conn.execute("PRAGMA query_only = ON")
