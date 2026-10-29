"""The fixed benchmark suite: ten realistic slow queries against the seeded shop database."""

from __future__ import annotations

import platform
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from querydoctor import __version__
from querydoctor.advisor import AdvisorConfig, ProgressCallback, analyze
from querydoctor.ingest import QueryInput
from querydoctor.models import FullReport


@dataclass(frozen=True)
class BenchQuery:
    """One benchmark query."""

    id: str
    title: str
    sql: str


BENCH_QUERIES: tuple[BenchQuery, ...] = (
    BenchQuery(
        "b01",
        "Customer order history",
        "SELECT id, total_cents, created_at FROM orders WHERE user_id = 1 "
        "ORDER BY created_at DESC LIMIT 20",
    ),
    BenchQuery(
        "b02",
        "Pending orders this quarter",
        "SELECT id, user_id, total_cents FROM orders "
        "WHERE status = 'pending' AND created_at >= '2025-10-01'",
    ),
    BenchQuery(
        "b03",
        "Order line items",
        "SELECT oi.id, p.name, oi.quantity FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id WHERE oi.order_id = 123456",
    ),
    BenchQuery(
        "b04",
        "Login by email",
        "SELECT id, name, plan FROM users WHERE email = 'user77777@example.com'",
    ),
    BenchQuery(
        "b05",
        "Product rating summary",
        "SELECT AVG(rating), COUNT(*) FROM reviews WHERE product_id = 7",
    ),
    BenchQuery(
        "b06",
        "Bulk purchases of a product",
        "SELECT order_id, quantity FROM order_items WHERE product_id = 1 AND quantity >= 4",
    ),
    BenchQuery(
        "b07",
        "Q1 revenue by customer",
        "SELECT user_id, SUM(total_cents) AS spend FROM orders "
        "WHERE created_at BETWEEN '2025-01-01' AND '2025-03-31' AND status = 'delivered' "
        "GROUP BY user_id ORDER BY spend DESC LIMIT 10",
    ),
    BenchQuery(
        "b08",
        "Refunded orders with customer",
        "SELECT u.email, o.total_cents FROM orders o JOIN users u ON u.id = o.user_id "
        "WHERE o.status = 'refunded' AND o.created_at >= '2025-09-01'",
    ),
    BenchQuery(
        "b09",
        "Best sellers this quarter",
        "SELECT oi.product_id, SUM(oi.quantity) AS units FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.created_at >= '2025-10-01' "
        "GROUP BY oi.product_id ORDER BY units DESC LIMIT 10",
    ),
    BenchQuery(
        "b10",
        "Customers with pending orders",
        "SELECT COUNT(*) FROM users u WHERE u.country = 'SG' AND u.plan = 'pro' "
        "AND u.created_at >= '2025-06-01' AND EXISTS "
        "(SELECT 1 FROM orders o WHERE o.user_id = u.id AND o.status = 'pending')",
    ),
)


class BenchEnvironment(BaseModel):
    """Where and how the benchmark was measured."""

    python: str
    platform: str
    sqlite: str
    querydoctor: str


class BenchResult(BaseModel):
    """A benchmark run: the full report plus its environment."""

    environment: BenchEnvironment
    report: FullReport


def run_bench(
    db_path: Path,
    *,
    progress: ProgressCallback | None = None,
    cfg: AdvisorConfig | None = None,
) -> BenchResult:
    """Run the fixed suite against ``db_path``."""
    queries = [QueryInput(id=q.id, sql=q.sql, title=q.title) for q in BENCH_QUERIES]
    report = analyze(db_path, queries, cfg or AdvisorConfig(), progress)
    env = BenchEnvironment(
        python=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        sqlite=sqlite3.sqlite_version,
        querydoctor=__version__,
    )
    return BenchResult(environment=env, report=report)
