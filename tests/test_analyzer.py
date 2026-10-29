from __future__ import annotations

from querydoctor.analyzer import find_problems, parse_access, plan_uses_index, summarize
from querydoctor.models import FindingKind, PlanNode, Severity


def node(detail: str, depth: int = 0, id_: int = 1) -> PlanNode:
    return PlanNode(id=id_, parent=0, depth=depth, detail=detail)


def kinds(plan: list[PlanNode], rows: dict[str, int] | None = None) -> set[FindingKind]:
    return {f.kind for f in find_problems(plan, rows or {})}


def test_parse_access_variants() -> None:
    assert parse_access("SCAN orders") == ("SCAN", "orders", None)
    assert parse_access("SCAN TABLE orders") == ("SCAN", "orders", None)
    assert parse_access("SEARCH orders USING INDEX idx_a (user_id=?)") == (
        "SEARCH",
        "orders",
        "INDEX idx_a (user_id=?)",
    )
    assert parse_access("USE TEMP B-TREE FOR ORDER BY") is None


def test_full_scan_severity_depends_on_table_size() -> None:
    big = find_problems([node("SCAN orders")], {"orders": 300_000})[0]
    small = find_problems([node("SCAN orders")], {"orders": 100})[0]
    unknown = find_problems([node("SCAN orders")], {})[0]
    assert (big.severity, small.severity, unknown.severity) == (
        Severity.HIGH,
        Severity.LOW,
        Severity.MEDIUM,
    )


def test_index_search_is_healthy() -> None:
    plan = [node("SEARCH orders USING INDEX idx_a (user_id=?)")]
    assert kinds(plan) == set()


def test_covering_index_scan_is_still_a_scan() -> None:
    assert FindingKind.FULL_SCAN in kinds([node("SCAN orders USING COVERING INDEX idx_a")])


def test_temp_sort_and_group_are_detected() -> None:
    plan = [node("SCAN t", id_=1), node("USE TEMP B-TREE FOR ORDER BY", id_=2)]
    assert FindingKind.TEMP_SORT in kinds(plan)
    plan = [node("SEARCH t USING INDEX i (a=?)"), node("USE TEMP B-TREE FOR GROUP BY")]
    assert kinds(plan) == {FindingKind.TEMP_GROUP}


def test_automatic_index_is_flagged() -> None:
    plan = [node("SEARCH o USING AUTOMATIC COVERING INDEX (user_id=?)")]
    assert kinds(plan) == {FindingKind.AUTO_INDEX}


def test_join_without_index_flagged_for_second_scan() -> None:
    plan = [node("SCAN a", id_=1), node("SCAN b", id_=2)]
    assert FindingKind.JOIN_WITHOUT_INDEX in kinds(plan)


def test_plan_uses_index_is_case_insensitive() -> None:
    plan = [node("SEARCH orders USING INDEX IDX_Orders_User (user_id=?)")]
    assert plan_uses_index(plan, "idx_orders_user")
    assert not plan_uses_index(plan, "idx_other")


def test_summarize() -> None:
    assert summarize([node("SCAN orders")]) == "scan orders"
    assert summarize([node("USE TEMP B-TREE FOR ORDER BY")]) == "no table access"
    assert "via INDEX idx_a" in summarize([node("SEARCH t USING INDEX idx_a (x=?)")])
