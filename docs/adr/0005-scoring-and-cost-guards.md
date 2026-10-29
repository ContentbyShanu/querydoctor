# ADR 0005: Scoring function and cost guards

- Status: accepted
- Date: 2026-10

## Context

The fastest index is not always the best one: it may be large or slow every insert. Ranking by
speedup alone would recommend bloated covering indexes for small gains.

## Decision

```
score = log2(speedup) / (1 + 0.5 * write_overhead + 2 * size_ratio)
```

- `log2` makes each doubling worth the same, so a 1,000x win does not drown out a 4x win.
- `write_overhead` is the relative slowdown of inserts, capped at 4.
- `size_ratio` is the index size divided by the database size.

Cost guards run before ranking:

- An index that more than doubles insert time must earn at least a 3x speedup.
- Any index after the first for a query must earn at least 1.5x on top of the previous state.
- A candidate must beat the 1.25x threshold and return an identical result set.

Confidence is `high` for at least 3x with stable timings (coefficient of variation at most
0.25) and an identical result, `medium` for at least 1.5x, otherwise `low`.

## Consequences

- Cheap, narrow indexes beat wide ones when they perform similarly.
- The weights are constants in `ranker.py` and are documented, not tuned per dataset.
- Write overhead is measured with a synthetic insert batch, so it is a relative indicator, not a
  prediction of production throughput.
