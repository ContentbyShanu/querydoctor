# ADR 0001: SQLite first, behind an engine interface

- Status: accepted
- Date: 2026-10

## Context

An index advisor is only credible if its claims can be checked by whoever clones the
repository. Requiring a PostgreSQL server (or Docker) before the first command runs would
filter out most reviewers, and the advisor logic itself (parse query, propose indexes, measure,
rank) does not depend on one particular database.

## Decision

The first engine is SQLite. It ships with Python, needs no server, and offers everything the
method needs: `EXPLAIN QUERY PLAN`, partial indexes, covering indexes, an online backup API and
`ANALYZE`. All database-specific behavior (schema reading, planning, timing, index inspection)
sits in `engine.py` behind the `Engine` protocol, and index SQL is produced in one place
(`Candidate.create_sql`).

## Consequences

- Anyone can run `querydoctor seed && querydoctor bench` in a minute with only `pip install`.
- SQLite plans differ from PostgreSQL plans; recommendations are not transferable between them.
- PostgreSQL support is a new `Engine` implementation (using `EXPLAIN (ANALYZE, BUFFERS)` and a
  sandbox database or `hypopg`), plus `CREATE INDEX CONCURRENTLY` in the migration writer. It is
  on the roadmap.
