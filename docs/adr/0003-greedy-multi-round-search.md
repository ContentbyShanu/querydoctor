# ADR 0003: Greedy, multi-round search per query

- Status: accepted
- Date: 2026-10

## Context

Some queries need more than one index (a join needs a lookup index on each side, for example),
and the best second index depends on the first. Exhaustively testing every combination is
exponential.

## Decision

For each query, up to `max_rounds` (default 3) rounds run. Each round generates candidates
against the current sandbox state (accepted indexes included), measures every candidate,
applies cost guards, and accepts the single best by score. Later rounds measure the gain on top
of what is already accepted.

If a later winner starts with the same columns as an accepted index (same table and predicate),
it replaces it: the old index is dropped, the new one is re-measured alone, and only the wider
index is recommended.

## Consequences

- Cost is linear in the number of candidates per round, not exponential.
- It can miss pairs of indexes that only help together, because each candidate is measured on its
  own before it is accepted. No query in the benchmark suite hits this, but a pairwise search is on
  the roadmap.
- Recommendations never contain an index that is a strict prefix of another recommended index.
