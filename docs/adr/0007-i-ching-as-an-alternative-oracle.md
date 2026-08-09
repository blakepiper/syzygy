# ADR 0007: I Ching as an alternative Oracle

- Status: accepted
- Date: 2026-08-09

## Context

M20 adds an I Ching consultation after M19 established a question-led Oracle.
The rite must decide how six lines are cast, whether change is read, and
whether a hexagram accompanies or replaces the Thoth card. These are
divinatory choices, not implementation details.

The source text is James Legge's 1882 translation in *The Sacred Books of the
East*, volume 16. Syzygy ships the judgment, Image, and six line texts for all
64 hexagrams with page-level citations to that edition.

## Decision

### Use the three-coin method

Each of six lines is formed from three equiprobable binary coin outcomes. A
tail counts two and a head counts three:

| Total | Line | Probability | Change |
|---:|---|---:|---|
| 6 | old yin | 1/8 | yin becomes yang |
| 7 | young yang | 3/8 | none |
| 8 | young yin | 3/8 | none |
| 9 | old yang | 1/8 | yang becomes yin |

Lines are cast from the bottom upward. The implementation mixes the same
`EntropyCollector` used by Sortes, derives one domain-separated digest per
line, and selects one of the eight equiprobable coin patterns through the
existing rejection sampler. It never uses `random.random()` or raw modulo.

The yarrow-stalk method is not a hidden configuration option. Its changing
line probabilities differ materially (old yin 1/16 and old yang 3/16), so
adding it later would require a visible ritual choice and a new cast-method
version.

### Read changing lines and the resulting hexagram

The primary hexagram's judgment and Image establish the situation. Only the
texts of changing lines are emphasized. Changing every old line produces the
resulting hexagram, whose judgment and Image describe the direction of change.
It is not treated as a second independent cast. With no changing lines, the
primary hexagram stands alone.

The six line values, method version, entropy digest, primary number, changing
line positions, and resulting number are committed before context building or
any provider call. Retry and recovery always reuse that cast.

### Make I Ching an alternative Oracle mode

The question screen offers Thoth or I Ching before the wheel. A consultation
contains exactly one chance object: one upright Thoth card or one six-line I
Ching cast, never both. Both modes retain SELF and COSMOS as supporting
context, subordinate to the question and chosen oracle.

The existing `oracle_consultations` table and `InterpretationContext` were
deliberately card-shaped. I Ching therefore receives a parallel append-only
table and state machine while reusing the question contract, astrology
ranking, provider boundary, structured result, recovery behavior, and archive.
This avoids nullable fields whose combinations could represent an invalid
two-oracle consultation.

## Consequences

- The UI and archive can state unambiguously which oracle was consulted.
- A cast is reproducible from its stored values and remains fixed across
  provider failure or application restart.
- Supporting another casting tradition requires an explicit product decision,
  version, probability tests, and UI treatment; it cannot silently change old
  readings.
- Legge's prose is provider input from the canonical resource, not model
  recollection or the tarot knowledge index.
