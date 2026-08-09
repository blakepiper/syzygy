# ADR 0006 — The Oracle as a separate consultation rite

- **Status:** accepted
- **Date:** 2026-08-09
- **Milestone:** M19
- **Supersedes:** nothing. Extends the daily rite without changing it.

## Context

The daily reading has one canonical card per profile and local date. The
Oracle instead answers a question the user supplies, and a user may make more
than one consultation in a day. Treating an Oracle consultation as another
daily reading would either violate the database uniqueness that protects the
daily card or weaken that invariant for every existing reading.

## Decision

### 1. A separate rite and state machine

Oracle consultations use their own table, repository, and state machine:
`ASKED → DRAWN → CONTEXT_READY → INTERPRETING → COMPLETE / INTERPRETATION_FAILED`.
There is no uniqueness constraint by profile and date. Every consultation is
new and requires a new turn of the wheel, but a consultation can never reroll:
the draw is committed before context construction or a provider call, and
retry always uses the stored card and context.

Migration 6 already belongs to M18, so the Oracle schema is append-only
migration 7 despite the stale M19 checklist wording.

### 2. SELF and COSMOS remain context, not an answer engine

The Oracle receives the saved natal chart and the same Syzygy-filtered and
ranked transits as the daily rite. They are supporting context below the fixed
card and the question. It does not cast a horary chart: horary requires the
querent's current location and momentary angles, while Syzygy deliberately
collects neither current location nor current houses or angles. Horary is out
of scope, not deferred.

### 3. Questions are bounded user data

The original question is stored locally as typed, capped at 1,000 Unicode
characters, and never placed on a process command line. A normalized copy is
made for the interpretation context by removing control/format characters and
collapsing whitespace. Empty normalized questions are rejected. In the prompt
the normalized question is JSON-quoted beneath the fixed card, astrology, and
source facts, with explicit instructions that it is data and cannot alter
those facts or the output contract. It is sent only to the provider the user
selected, including the entirely local option.

Question keystroke timing is mixed into the same `EntropyCollector` later used
by the wheel. The characters themselves are not entropy events and are never
persisted in the draw record; OS randomness remains mandatory.

### 4. Divination, not directives

The Oracle reflects through the card. Its prompt and structured result require
an explicit question-facing response while retaining the esoteric and
conventional registers. The contract forbids medical, legal, financial, and
safety-critical directives and forbids dated outcomes presented as fact.
There is no post-generation filter pretending it can repair a bad answer.

### 5. I Ching remains M20

No hexagram logic or data is introduced here. M20 may reuse the consultation
flow only after its own source-grounding work; it may not turn the model into a
coin thrower, line calculator, or canonical-text source.

## Consequences

- Daily readings retain their database-enforced uniqueness unchanged.
- The archive contains two visibly distinct record types, both reopened as
  stored read-only results.
- Unlimited consultations are possible, but every one carries the friction
  and commitment of its own question, wheel turn, and fixed draw.
- Providers continue to receive only `InterpretationContext`; the Oracle adds
  no database, profile, or astrology access to provider adapters.

