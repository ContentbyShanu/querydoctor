"""Deterministic generator for a realistic e-commerce database.

Only primary keys are indexed, so the dataset is full of the slow queries QueryDoctor exists
to fix. The same ``seed`` always produces the same data.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    plan TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    country TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    rating INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL
);
"""

BASE_ROWS = {
    "users": 100_000,
    "products": 20_000,
    "orders": 300_000,
    "order_items": 500_000,
    "reviews": 100_000,
}

COUNTRIES = ["IN", "US", "GB", "DE", "FR", "BR", "JP", "CA", "AU", "SG"]
PLANS = ["free", "free", "free", "basic", "basic", "pro", "team"]
CATEGORIES = [
    "electronics",
    "books",
    "home",
    "garden",
    "toys",
    "sports",
    "beauty",
    "grocery",
    "fashion",
    "office",
]
BRANDS = [f"brand-{i:02d}" for i in range(40)]
STATUSES = (
    ["delivered"] * 70 + ["shipped"] * 12 + ["pending"] * 8 + ["cancelled"] * 6 + ["refunded"] * 4
)
TITLES = ["Great value", "Works as described", "Not for me", "Excellent", "Disappointed", "Solid"]
_FIRST_DAY = date(2023, 1, 1)
_DAYS = 1096
_BATCH = 50_000


def _dates() -> list[str]:
    return [(_FIRST_DAY + timedelta(days=i)).isoformat() for i in range(_DAYS)]


def _batches(rows: Iterator[tuple[object, ...]]) -> Iterator[list[tuple[object, ...]]]:
    batch: list[tuple[object, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= _BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


def _skewed(rng: random.Random, n: int) -> int:
    """Pick an id in ``1..n`` with a bias toward low ids (a few very active customers)."""
    return int((rng.random() ** 1.6) * n) + 1


def _users(rng: random.Random, n: int, days: list[str]) -> Iterator[tuple[object, ...]]:
    for i in range(1, n + 1):
        yield (
            i,
            f"user{i}@example.com",
            f"User {i}",
            rng.choice(COUNTRIES),
            rng.choice(PLANS),
            rng.choice(days),
            1 if rng.random() < 0.92 else 0,
        )


def _products(rng: random.Random, n: int) -> Iterator[tuple[object, ...]]:
    for i in range(1, n + 1):
        yield (
            i,
            f"SKU-{i:06d}",
            f"Product {i}",
            rng.choice(CATEGORIES),
            rng.choice(BRANDS),
            rng.randint(199, 99_999),
            rng.randint(0, 5_000),
        )


def _orders(
    rng: random.Random, n: int, n_users: int, days: list[str]
) -> Iterator[tuple[object, ...]]:
    for i in range(1, n + 1):
        yield (
            i,
            _skewed(rng, n_users),
            rng.choice(STATUSES),
            rng.randint(500, 250_000),
            rng.choice(COUNTRIES),
            rng.choice(days),
        )


def _items(
    rng: random.Random, n: int, n_orders: int, n_products: int
) -> Iterator[tuple[object, ...]]:
    for i in range(1, n + 1):
        yield (
            i,
            rng.randint(1, n_orders),
            _skewed(rng, n_products),
            rng.randint(1, 5),
            rng.randint(199, 99_999),
        )


def _reviews(
    rng: random.Random, n: int, n_products: int, n_users: int, days: list[str]
) -> Iterator[tuple[object, ...]]:
    for i in range(1, n + 1):
        yield (
            i,
            _skewed(rng, n_products),
            rng.randint(1, n_users),
            rng.choices([1, 2, 3, 4, 5], weights=[6, 6, 12, 28, 48])[0],
            rng.choice(days),
            rng.choice(TITLES),
        )


def row_counts(scale: float) -> dict[str, int]:
    """Row count per table for a given scale factor (1.0 is roughly one million rows)."""
    return {t: max(50, int(n * scale)) for t, n in BASE_ROWS.items()}


def seed_database(
    path: Path,
    *,
    scale: float = 1.0,
    seed: int = 42,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, int]:
    """Create ``path`` from scratch and fill it. Returns the row count per table."""
    counts = row_counts(scale)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rng = random.Random(seed)
    days = _dates()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript(SCHEMA)
        generators: list[tuple[str, int, Iterator[tuple[object, ...]], int]] = [
            ("users", counts["users"], _users(rng, counts["users"], days), 7),
            ("products", counts["products"], _products(rng, counts["products"]), 7),
            (
                "orders",
                counts["orders"],
                _orders(rng, counts["orders"], counts["users"], days),
                6,
            ),
            (
                "order_items",
                counts["order_items"],
                _items(rng, counts["order_items"], counts["orders"], counts["products"]),
                5,
            ),
            (
                "reviews",
                counts["reviews"],
                _reviews(rng, counts["reviews"], counts["products"], counts["users"], days),
                6,
            ),
        ]
        for table, total, rows, width in generators:
            placeholders = ",".join("?" * width)
            done = 0
            for batch in _batches(rows):
                conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", batch)
                done += len(batch)
                if progress:
                    progress(table, done, total)
            conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
    return counts
