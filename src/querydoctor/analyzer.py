"""Query plan analysis: turn ``EXPLAIN QUERY PLAN`` output into actionable findings."""

from __future__ import annotations

import re

from querydoctor.models import Finding, FindingKind, PlanNode, Severity

_ACCESS = re.compile(
    r"^(?P<op>SCAN|SEARCH)\s+(?:TABLE\s+)?(?P<table>[\w\"]+)(?:\s+AS\s+\w+)?"
    r"(?:\s+USING\s+(?P<using>.*))?$",
    re.IGNORECASE,
)
LARGE_TABLE_ROWS = 10_000


def parse_access(detail: str) -> tuple[str, str, str | None] | None:
    """Parse a plan line into ``(operation, table, using)`` or ``None`` if it is not an access."""
    match = _ACCESS.match(detail.strip())
    if not match:
        return None
    table = match.group("table").strip('"')
    return match.group("op").upper(), table, match.group("using")


def plan_uses_index(plan: list[PlanNode], index_name: str) -> bool:
    """True if any plan line references the index by name."""
    needle = index_name.lower()
    return any(needle in node.detail.lower() for node in plan)


def _severity(rows: int | None) -> Severity:
    if rows is None:
        return Severity.MEDIUM
    if rows >= LARGE_TABLE_ROWS:
        return Severity.HIGH
    return Severity.LOW


def find_problems(plan: list[PlanNode], table_rows: dict[str, int]) -> list[Finding]:
    """Detect scans, temporary sorts and joins that lack index support."""
    findings: list[Finding] = []
    top_level_accesses = 0
    for node in plan:
        detail = node.detail
        upper = detail.upper()
        access = parse_access(detail)
        if access:
            op, table, using = access
            top_level_accesses += 1 if node.depth == 0 else 0
            rows = table_rows.get(table)
            size = f" ({rows:,} rows)" if rows else ""
            is_full = op == "SCAN" and (using is None or "COVERING INDEX" in using.upper())
            if "AUTOMATIC" in upper:
                findings.append(
                    Finding(
                        kind=FindingKind.AUTO_INDEX,
                        severity=Severity.HIGH,
                        table=table,
                        message=f"SQLite builds a temporary index on {table} for every execution.",
                    )
                )
            elif is_full:
                findings.append(
                    Finding(
                        kind=FindingKind.FULL_SCAN,
                        severity=_severity(rows),
                        table=table,
                        message=f"Full scan of {table}{size}.",
                    )
                )
                if top_level_accesses > 1 and node.depth == 0:
                    findings.append(
                        Finding(
                            kind=FindingKind.JOIN_WITHOUT_INDEX,
                            severity=_severity(rows),
                            table=table,
                            message=f"Join reads {table} in full for each outer row.",
                        )
                    )
        elif "USE TEMP B-TREE FOR ORDER BY" in upper:
            findings.append(
                Finding(
                    kind=FindingKind.TEMP_SORT,
                    severity=Severity.MEDIUM,
                    message="Rows are sorted in a temporary structure.",
                )
            )
        elif "USE TEMP B-TREE FOR" in upper and "GROUP BY" in upper:
            findings.append(
                Finding(
                    kind=FindingKind.TEMP_GROUP,
                    severity=Severity.MEDIUM,
                    message="Groups are built in a temporary structure.",
                )
            )
    return findings


def summarize(plan: list[PlanNode]) -> str:
    """One-line description of how the plan reads data, for explanations."""
    parts = []
    for node in plan:
        access = parse_access(node.detail)
        if access:
            op, table, using = access
            parts.append(
                f"{op.lower()} {table}" + (f" via {using.split(' (')[0]}" if using else "")
            )
    return "; ".join(parts) if parts else "no table access"
