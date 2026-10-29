# ADR 0004: Composite index column order

- Status: accepted
- Date: 2026-10

## Context

A b-tree index can seek on a prefix of its columns. After a range condition, later columns can
no longer be used to seek. Column order therefore decides whether an index is useful.

## Decision

Candidate columns are ordered as follows:

1. Equality filter columns first, most selective first (highest estimated distinct ratio).
2. Then at most one range column (`>`, `>=`, `<`, `<=`, `BETWEEN`).
3. If there is no range column, ordering columns from `ORDER BY` follow the equality columns so
   rows come out already sorted and the temporary sort disappears.
4. Join keys are appended after filter equality columns.
5. Covering variants append the remaining selected columns, up to five columns in total.

Selectivity comes from a distinct-count over a leading sample of the table (50,000 rows). Rowid
primary keys are never indexed or repeated, because every SQLite index already contains the
rowid.

## Consequences

- The most common textbook shapes (`user_id, created_at`) are always among the candidates.
- The final choice is still made by measurement, so a wrong guess costs time, never correctness.
- Predicates under `OR`, expressions such as `lower(email)`, and `LIKE` are not turned into
  index columns yet.
