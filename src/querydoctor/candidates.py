"""Index candidate generation.

The generator reads a query with sqlglot, classifies every column reference (equality filter,
range filter, join key, ordering, grouping, projection) and proposes single-column, composite,
covering and partial indexes. Composite column order follows the classic rule: equality columns
first (most selective first), then at most one range column, because a b-tree cannot keep
seeking after a range.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from querydoctor.models import Candidate

MAX_CANDIDATES = 16
MAX_PER_TABLE = 6
MAX_COVERING_COLUMNS = 5
PARTIAL_MAX_FRACTION = 0.2
PARTIAL_MAX_DISTINCT_RATIO = 0.01


@dataclass
class TableUsage:
    """How one table's columns are used by a query."""

    name: str
    equality: list[str] = field(default_factory=list)
    equality_literals: dict[str, str] = field(default_factory=dict)
    equality_is_single: dict[str, bool] = field(default_factory=dict)
    range: list[str] = field(default_factory=list)
    join: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    group: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)

    def add(self, bucket: list[str], column: str) -> None:
        """Append ``column`` to ``bucket`` once."""
        if column not in bucket:
            bucket.append(column)

    @property
    def touched(self) -> list[str]:
        """Every column that appears in a predicate, join, ordering or grouping."""
        seen: list[str] = []
        for bucket in (self.equality, self.join, self.range, self.group, self.order):
            for col in bucket:
                if col not in seen:
                    seen.append(col)
        return seen


class Stats:
    """Optional column statistics used to order equality columns and pick partial indexes."""

    def distinct_ratio(self, table: str, column: str) -> float:
        """Approximate fraction of distinct values in a column (1.0 means unique)."""
        return 0.5

    def value_fraction(self, table: str, column: str, literal: str) -> float | None:
        """Fraction of rows holding ``literal`` in ``column`` or ``None`` if unknown."""
        return None


def _unwrap(node: exp.Expr | None) -> exp.Expr | None:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _conjuncts(node: exp.Expr | None) -> list[exp.Expr]:
    node = _unwrap(node)
    if node is None:
        return []
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    return [node]


def _is_literal(node: exp.Expr | None) -> bool:
    node = _unwrap(node)
    if isinstance(node, exp.Literal):
        return True
    return isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal)


class _Resolver:
    """Maps column references to real tables, handling aliases and unqualified names."""

    def __init__(self, statement: exp.Expr, schema: dict[str, list[str]]) -> None:
        self.schema = schema
        self.aliases: dict[str, str] = {}
        self.tables: list[str] = []
        for table in statement.find_all(exp.Table):
            real = table.name
            if real not in schema:
                continue
            self.aliases[(table.alias or real).lower()] = real
            self.aliases.setdefault(real.lower(), real)
            if real not in self.tables:
                self.tables.append(real)

    def resolve(self, column: exp.Column) -> tuple[str, str] | None:
        """Return ``(table, column)`` for a column reference, or ``None`` if ambiguous."""
        name = column.name
        if column.table:
            table = self.aliases.get(column.table.lower())
            if table and name in self.schema[table]:
                return table, name
            return None
        owners = [t for t in self.tables if name in self.schema[t]]
        return (owners[0], name) if len(owners) == 1 else None


def _classify(condition: exp.Expr, resolver: _Resolver, usage: dict[str, TableUsage]) -> None:
    """Record what one top-level condition says about its columns."""
    condition = _unwrap(condition) or condition

    def column_of(node: exp.Expr | None) -> tuple[str, str] | None:
        node = _unwrap(node)
        return resolver.resolve(node) if isinstance(node, exp.Column) else None

    if isinstance(condition, exp.EQ):
        left, right = column_of(condition.left), column_of(condition.right)
        if left and right:
            if left[0] != right[0]:
                usage[left[0]].add(usage[left[0]].join, left[1])
                usage[right[0]].add(usage[right[0]].join, right[1])
            return
        col, other = (left, condition.right) if left else (right, condition.left)
        literal = _unwrap(other)
        if col and literal is not None and _is_literal(literal):
            tbl = usage[col[0]]
            tbl.add(tbl.equality, col[1])
            tbl.equality_literals[col[1]] = literal.sql(dialect="sqlite")
            tbl.equality_is_single[col[1]] = True
    elif isinstance(condition, exp.In):
        col = column_of(condition.this)
        values = condition.expressions
        if col and values and all(_is_literal(v) for v in values):
            tbl = usage[col[0]]
            tbl.add(tbl.equality, col[1])
            tbl.equality_is_single[col[1]] = len(values) == 1
    elif isinstance(condition, exp.GT | exp.GTE | exp.LT | exp.LTE):
        left, right = column_of(condition.left), column_of(condition.right)
        col = left if left and _is_literal(condition.right) else None
        col = col or (right if right and _is_literal(condition.left) else None)
        if col:
            usage[col[0]].add(usage[col[0]].range, col[1])
    elif isinstance(condition, exp.Between):
        col = column_of(condition.this)
        if col:
            usage[col[0]].add(usage[col[0]].range, col[1])


def extract_usage(sql: str, schema: dict[str, list[str]]) -> dict[str, TableUsage]:
    """Classify how each known table's columns are used in ``sql``."""
    statement = sqlglot.parse_one(sql, read="sqlite")
    resolver = _Resolver(statement, schema)
    usage = {t: TableUsage(t) for t in resolver.tables}
    if not usage:
        return usage
    for where in statement.find_all(exp.Where):
        for cond in _conjuncts(where.this):
            _classify(cond, resolver, usage)
    for join in statement.find_all(exp.Join):
        for cond in _conjuncts(join.args.get("on")):
            _classify(cond, resolver, usage)
    for order in statement.find_all(exp.Order):
        resolved = []
        for item in order.expressions:
            inner = item.this if isinstance(item, exp.Ordered) else item
            col = resolver.resolve(inner) if isinstance(inner, exp.Column) else None
            resolved.append(col)
        if resolved and all(resolved) and len({c[0] for c in resolved if c}) == 1:
            for col in resolved:
                if col:
                    usage[col[0]].add(usage[col[0]].order, col[1])
    for group in statement.find_all(exp.Group):
        for item in group.expressions:
            col = resolver.resolve(item) if isinstance(item, exp.Column) else None
            if col:
                usage[col[0]].add(usage[col[0]].group, col[1])
    for select in statement.find_all(exp.Select):
        for projection in select.expressions:
            for column in projection.find_all(exp.Column):
                col = resolver.resolve(column)
                if col:
                    usage[col[0]].add(usage[col[0]].selected, col[1])
    for order in statement.find_all(exp.Order):
        for column in order.find_all(exp.Column):
            col = resolver.resolve(column)
            if col:
                usage[col[0]].add(usage[col[0]].selected, col[1])
    return usage


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _name(table: str, columns: list[str], suffix: str = "") -> str:
    base = _slug(f"idx_{table}_{'_'.join(columns)}" + (f"_{suffix}" if suffix else ""))
    if len(base) <= 56:
        return base
    digest = hashlib.sha1(base.encode()).hexdigest()[:6]
    return f"{base[:49]}_{digest}"


def _covered_by_existing(
    table: str,
    columns: list[str],
    where: str | None,
    existing: list[dict[str, object]],
    primary_key: list[str],
) -> bool:
    """True if an existing index (or the integer primary key) already serves the candidate."""
    if len(primary_key) == 1 and columns[0] == primary_key[0] and where is None:
        return True
    for idx in existing:
        idx_cols = list(idx["columns"])  # type: ignore[call-overload]
        idx_where = idx.get("where")
        if idx_cols[: len(columns)] == columns and (idx_where is None or idx_where == where):
            return True
    return False


def generate_candidates(
    sql: str,
    schema: dict[str, list[str]],
    existing: dict[str, list[dict[str, object]]],
    primary_keys: dict[str, list[str]],
    stats: Stats | None = None,
) -> list[Candidate]:
    """Propose indexes that could speed up ``sql``, skipping ones that already exist."""
    stats = stats or Stats()
    usage = extract_usage(sql, schema)
    found: dict[tuple[str, tuple[str, ...], str], Candidate] = {}

    for table, use in usage.items():
        pk = primary_keys.get(table, [])
        rowid = set(pk) if len(pk) == 1 else set()
        filters = sorted(
            (c for c in use.equality if c not in rowid),
            key=lambda c: (-stats.distinct_ratio(table, c), c),
        )
        joins = [c for c in use.join if c not in filters and c not in rowid]
        rng = [c for c in use.range if c not in filters and c not in rowid]
        order = [c for c in use.order if c not in filters and c not in rowid]

        def make(
            cols: list[str],
            kind: str,
            why: str,
            where: str | None = None,
            suffix: str = "",
            _table: str = table,
        ) -> Candidate:
            return Candidate(
                table=_table,
                columns=cols,
                where=where,
                kind=kind,
                name=_name(_table, cols, suffix),
                rationale=why,
            )

        composites: list[list[str]] = []
        if filters and rng:
            composites.append([*filters, rng[0]])
        if filters and order and not rng:
            composites.append([*filters, *order])
        if filters and joins:
            composites.append([*filters, *joins])
        if len(filters) > 1:
            composites.append(list(filters))
        if joins and not filters:
            composites.append(list(joins))
        if not filters and not joins and use.group:
            composites.append(list(use.group))
        if not filters and rng and order and rng[0] == order[0]:
            composites.append([rng[0]])

        local: dict[tuple[str, tuple[str, ...], str], Candidate] = {}
        for cols in composites:
            kind = "composite" if len(cols) > 1 else "single"
            cand = make(cols, kind, _why(cols, use))
            local.setdefault(cand.signature, cand)
        for col in (c for c in use.touched if c not in rowid):
            cand = make([col], "single", f"Direct lookup on {table}.{col}.")
            local.setdefault(cand.signature, cand)

        base = composites[0] if composites else ([use.touched[0]] if use.touched else [])
        extra = [c for c in use.selected if c not in base and c not in rowid]
        if base and extra and len(base) + len(extra) <= MAX_COVERING_COLUMNS:
            cand = make(
                [*base, *extra],
                "covering",
                "Answers the query from the index alone, with no table lookups.",
                suffix="cov",
            )
            local.setdefault(cand.signature, cand)

        for col, literal in use.equality_literals.items():
            if not use.equality_is_single.get(col):
                continue
            if stats.distinct_ratio(table, col) > PARTIAL_MAX_DISTINCT_RATIO:
                continue
            fraction = stats.value_fraction(table, col, literal)
            rest = [c for c in [*filters, *rng, *order] if c != col] or list(joins)
            if fraction is not None and fraction <= PARTIAL_MAX_FRACTION and rest:
                where = f"{col} = {literal}"
                cand = make(
                    rest,
                    "partial",
                    f"Indexes only rows where {where} (about {fraction * 100:.0f}% of the table).",
                    where=where,
                    suffix=f"where_{_slug(col)}_{_slug(literal)}",
                )
                local.setdefault(cand.signature, cand)

        usable = [c for c in local.values() if _usable(c, existing, primary_keys)]
        usable.sort(key=_rank_key)
        for cand in usable[:MAX_PER_TABLE]:
            found.setdefault(cand.signature, cand)

    return sorted(found.values(), key=_rank_key)[:MAX_CANDIDATES]


_PRIORITY = {"partial": 0, "composite": 1, "covering": 2, "single": 3}


def _rank_key(cand: Candidate) -> tuple[int, int, str]:
    return (_PRIORITY[cand.kind], -len(cand.columns), cand.name)


def _usable(
    cand: Candidate,
    existing: dict[str, list[dict[str, object]]],
    primary_keys: dict[str, list[str]],
) -> bool:
    if not cand.columns or len(cand.columns) > MAX_COVERING_COLUMNS:
        return False
    return not _covered_by_existing(
        cand.table,
        cand.columns,
        cand.where,
        existing.get(cand.table, []),
        primary_keys.get(cand.table, []),
    )


def _why(columns: list[str], use: TableUsage) -> str:
    parts = []
    eq = [c for c in columns if c in use.equality or c in use.join]
    if eq:
        parts.append(f"equality/join on {', '.join(eq)}")
    rng = [c for c in columns if c in use.range]
    if rng:
        parts.append(f"range on {', '.join(rng)}")
    tail = [c for c in columns if c in use.order and c not in eq and c not in rng]
    if tail:
        parts.append(f"ordered by {', '.join(tail)}")
    return "Composite index: " + "; ".join(parts) + "." if parts else "Composite index."
