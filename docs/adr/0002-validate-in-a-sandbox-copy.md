# ADR 0002: Validate every candidate in a sandbox copy

- Status: accepted
- Date: 2026-10

## Context

Most advisors estimate benefit from planner cost numbers, which are guesses. We want proof:
real timings, an identical result set, and a measured price in disk and write speed. Measuring
requires creating indexes, which must never happen on the database being analyzed.

## Decision

`Sandbox` copies the database with SQLite's backup API into a temporary directory. On the copy
it runs `ANALYZE`, then for each candidate: records the baseline write cost, creates the index,
checks the plan actually uses it, times the query (median of 3 to 7 runs after a warm-up),
compares a digest of the result set with the baseline, measures insert overhead inside a
rolled-back transaction, and drops the index. The original is opened with `mode=ro`, and user
SQL runs with `PRAGMA query_only = ON`.

## Consequences

- The user's database cannot be modified, even by a bug in the candidate generator.
- Analysis time grows with database size because of the copy; acceptable for development-size
  data and documented as a limitation.
- Results are measured on the local machine, so absolute times vary; ratios are what matter.
- A candidate the planner ignores is discarded immediately without timing, which saves most of
  the run time.
