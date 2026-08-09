# ADR 0004: Cache chart and cosmos summaries separately

Status: accepted (2026-08-08)

## Decision

Model-generated chart and cosmos summaries live in the append-only migration
5 table `interpretive_summaries`, never in `readings` or `profiles`.

- A natal summary has the stable key `(profile_id, natal_summary, "")` and is
  generated once for the life of that immutable saved chart.
- A cosmos summary has the daily key
  `(profile_id, cosmos_summary, consultation_local_date)`.
- Only successful structured results are cached. A failed call leaves no row,
  so the same on-demand UI action is an honest retry.
- The context and provenance are retained beside the result. The non-null
  `scope_date` makes SQLite's primary key enforce one canonical entry even for
  the undated natal scope.

## Consequences

Opening either screen is free: it displays a cached summary if one exists and
otherwise waits for `[G]`. Summary generation cannot draw a card, consume the
daily reading slot, or advance `ReadingStatus`; its service has no sortes or
reading-store dependency. Profile deletion removes its summaries in the same
transaction as its readings and profile row.
