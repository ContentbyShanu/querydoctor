from __future__ import annotations

import pytest

from querydoctor.candidates import Stats, extract_usage, generate_candidates

SCHEMA = {
    "orders": ["id", "user_id", "status", "total_cents", "created_at", "country"],
    "users": ["id", "email", "country", "plan", "created_at"],
    "order_items": ["id", "order_id", "product_id", "quantity"],
}
PKS = {"orders": ["id"], "users": ["id"], "order_items": ["id"]}


def cands(sql: str, existing: dict | None = None, stats: Stats | None = None) -> list:
    return generate_candidates(sql, SCHEMA, existing or {}, PKS, stats)


def creates(sql: str, **kw: object) -> list[str]:
    return [c.create_sql for c in cands(sql, **kw)]  # type: ignore[arg-type]


class FakeStats(Stats):
    def __init__(self, ratios: dict[str, float], fractions: dict[str, float]) -> None:
        self.ratios, self.fractions = ratios, fractions

    def distinct_ratio(self, table: str, column: str) -> float:
        return self.ratios.get(column, 0.5)

    def value_fraction(self, table: str, column: str, literal: str) -> float | None:
        return self.fractions.get(column)


def test_usage_classifies_columns() -> None:
    usage = extract_usage(
        "SELECT o.id, o.total_cents FROM orders o WHERE o.user_id = 5 "
        "AND o.created_at >= '2025-01-01' AND o.status IN ('a','b') ORDER BY o.created_at",
        SCHEMA,
    )["orders"]
    assert usage.equality == ["user_id", "status"]
    assert usage.range == ["created_at"]
    assert usage.order == ["created_at"]
    assert usage.equality_is_single == {"user_id": True, "status": False}


def test_usage_resolves_aliases_and_unqualified_columns() -> None:
    usage = extract_usage(
        "SELECT email FROM users u JOIN orders o ON o.user_id = u.id WHERE plan = 'pro'", SCHEMA
    )
    assert usage["users"].equality == ["plan"]
    assert usage["orders"].join == ["user_id"]
    assert usage["users"].join == ["id"]


def test_ambiguous_unqualified_column_is_ignored() -> None:
    usage = extract_usage(
        "SELECT 1 FROM users u JOIN orders o ON o.user_id = u.id WHERE country = 'IN'", SCHEMA
    )
    assert usage["users"].equality == []
    assert usage["orders"].equality == []


def test_unknown_tables_are_ignored() -> None:
    assert extract_usage("SELECT * FROM nothing WHERE a = 1", SCHEMA) == {}


def test_equality_columns_come_before_range_column() -> None:
    sql = "SELECT id FROM orders WHERE created_at >= '2025-01-01' AND user_id = 5"
    assert "CREATE INDEX idx_orders_user_id_created_at ON orders (user_id, created_at)" in creates(
        sql
    )


def test_equality_columns_are_ordered_by_selectivity() -> None:
    stats = FakeStats({"status": 0.001, "user_id": 0.4}, {})
    sql = "SELECT id FROM orders WHERE status = 'x' AND user_id = 5 AND created_at > '2025'"
    first = cands(sql, stats=stats)[0]
    assert first.columns == ["user_id", "status", "created_at"]


def test_order_by_follows_equality_when_no_range() -> None:
    sql = "SELECT id FROM orders WHERE user_id = 5 ORDER BY created_at DESC"
    assert any(c.columns == ["user_id", "created_at"] for c in cands(sql))


def test_covering_candidate_includes_selected_columns_but_not_rowid() -> None:
    sql = "SELECT id, total_cents FROM orders WHERE user_id = 5"
    cov = [c for c in cands(sql) if c.kind == "covering"]
    assert cov
    assert cov[0].columns == ["user_id", "total_cents"]


def test_primary_key_lookups_are_never_suggested() -> None:
    assert cands("SELECT email FROM users WHERE id = 5") == []


def test_existing_index_suppresses_candidate() -> None:
    existing = {"orders": [{"name": "i", "columns": ["user_id", "created_at"], "where": None}]}
    sql = "SELECT id FROM orders WHERE user_id = 5 AND created_at > '2025'"
    names = [c.columns for c in cands(sql, existing)]
    assert ["user_id", "created_at"] not in names
    assert ["user_id"] not in names


def test_partial_index_for_rare_low_cardinality_value() -> None:
    stats = FakeStats({"status": 0.0001}, {"status": 0.08})
    sql = "SELECT id FROM orders WHERE status = 'pending' AND created_at >= '2025-10-01'"
    partial = [c for c in cands(sql, stats=stats) if c.kind == "partial"]
    assert partial
    assert partial[0].where == "status = 'pending'"
    assert partial[0].columns == ["created_at"]
    assert partial[0].create_sql.endswith("WHERE status = 'pending'")


def test_no_partial_index_for_high_cardinality_or_common_values() -> None:
    sql = "SELECT id FROM orders WHERE status = 'pending' AND created_at >= '2025-10-01'"
    high_cardinality = FakeStats({"status": 0.5}, {"status": 0.01})
    common_value = FakeStats({"status": 0.0001}, {"status": 0.7})
    assert not [c for c in cands(sql, stats=high_cardinality) if c.kind == "partial"]
    assert not [c for c in cands(sql, stats=common_value) if c.kind == "partial"]


def test_join_columns_become_candidates() -> None:
    sql = "SELECT 1 FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.user_id = 3"
    found = creates(sql)
    assert any("ON order_items (order_id" in s for s in found)
    assert any("ON orders (user_id" in s for s in found)


def test_candidates_are_unique_and_capped() -> None:
    result = cands(
        "SELECT o.id, u.email FROM orders o JOIN users u ON u.id = o.user_id "
        "WHERE o.status = 'a' AND o.created_at > '1' AND u.plan = 'p' AND u.country = 'c' "
        "ORDER BY o.created_at"
    )
    assert len({c.signature for c in result}) == len(result)
    assert len(result) <= 16


def test_long_names_stay_short_and_unique() -> None:
    sql = (
        "SELECT id, total_cents, country FROM orders WHERE user_id = 1 AND status = 'a' "
        "AND created_at > '1'"
    )
    names = [c.name for c in cands(sql)]
    assert all(len(n) <= 56 for n in names)
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT id FROM orders"])
def test_queries_without_predicates_yield_nothing_useful(sql: str) -> None:
    assert all(c.kind != "partial" for c in cands(sql))


def test_group_by_only_query_proposes_group_index() -> None:
    sql = "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id"
    assert any(c.columns == ["user_id"] for c in cands(sql))


def test_rollback_sql() -> None:
    cand = cands("SELECT id FROM orders WHERE user_id = 1")[0]
    assert cand.rollback_sql == f"DROP INDEX IF EXISTS {cand.name}"
