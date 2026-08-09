# ADR 0008: The Oracle as figure and ground

- Status: accepted
- Date: 2026-08-09

## Context

M19 made the Oracle a question-led rite with one Thoth card. M20 added an I
Ching cast as an *alternative* mode, and ADR 0007 recorded that choice. Using
the instrument since then exposed two problems with the mode switch.

The first is that choosing the oracle is a decision the querent has to make
before they know anything, and there is no basis on which to make it. Nothing
about a question tells you whether a card or a hexagram will answer it better;
the choice is arbitrary, and an arbitrary choice presented as meaningful is
exactly the kind of false significance the rest of Syzygy refuses.

The second is that the mode switch spends the instrument's two chance objects
on the same job. A card and a hexagram were each being asked to be the whole
answer, which made them competitors — the objection ADR 0007 recorded and did
not resolve, only avoided by keeping them apart.

This ADR supersedes ADR 0007's *alternative Oracle mode* decision and, for the
Oracle only, ADR 0006 section 2's inclusion of COSMOS. Everything else in both
records stands.

## Decision

### 1. One rite, two chance objects, disjoint roles

Every Oracle consultation carries both objects, drawn from one turn of the
wheel, with roles fixed by Syzygy in the prompt contract:

| Object | Role |
|---|---|
| Hexagram Judgment (+ trigrams) | **the ground** — the character of the time the question is asked in |
| The Thoth card | **the figure** — the specific thing the oracle puts in front of the querent |
| Changing lines, resulting hexagram | where the ground is unstable, and its direction |
| The Image | conduct — how to bear oneself in it |

The model is never asked which object governs, and never asked to reconcile
them. There is no mode to choose, in the TUI, the CLI, or storage.

### 2. Why figure and ground rather than a topical split

A figure and its ground cannot contradict each other. They can only qualify
each other. The Tower in a time of Waiting reads differently from the Tower in
a time of Great Vigour, and no arbiter is needed to decide which is right —
the reading is the relation between them. This is what dissolves ADR 0007's
two-competing-oracles objection: structurally, by what the objects are asked to
be, not by instructing the model to be careful.

Alternatives considered and rejected:

- **What it is / where it goes.** The card names the thing, the cast names the
  trajectory. Rejected because 17.8% of casts have no changing line, and on
  those the cast's entire role goes empty — a role that vanishes on one
  consultation in six is not a role.
- **Inner / outer.** Redundant: a hexagram already encodes inner and outer in
  its lower and upper trigrams. Layering a second inner/outer axis over that
  says the same word twice.
- **Roles varying by question type.** Requires classifying the question, and
  only the model could classify it. That is the same reason horary is out of
  scope: a fact the instrument cannot fix is a fact the model would decide.
- **Leaving the tension unresolved as information.** Produces
  on-one-hand/on-the-other prose, which is the failure mode this design exists
  to prevent.

### 3. No correspondence between the 64 and the 78

No mapping between hexagrams and cards is used, and none may be invented.
There is no canonical one: the counts do not divide, the published attempts are
contested and mutually inconsistent, and Crowley practising both systems is
biography, not a table. Resolution of the two objects is structural — figure
in ground — and nothing else.

For the record: no such table exists anywhere in this repository. It was
considered in design discussion and rejected, never built. There is nothing to
remove.

### 4. Transits leave the Oracle

The Oracle receives SELF (the natal chart) and its two chance objects. It does
not receive the day's transits, and `oracle-v2` contains no transit block.

A question is usually about a horizon a transit is not on. A Moon aspect exact
for four hours will be woven in earnest into an answer about a decision six
months out, with nothing in the text telling the reader it will be gone by
dinner. That is an accuracy defect, not a matter of taste.

The natal chart is retained. It is the member of the trio the card can actually
speak to: both use decans, planets, signs, and elements, while a hexagram has
no astrological hook at all. The daily rite keeps its transits unchanged,
because a daily reading *is* about today.

Horary stays out of scope for its original reason: it needs current location
and momentary angles, which `AGENTS.md` forbids.

### 5. One entropy collection, two derivations

The question's keystrokes and one turn of the wheel feed a single
`EntropyCollector`. The card draw and each of the six lines come from
domain-separated derivations of it: `sortes.draw.draw_card` selects over the
digest directly, and `iching.cast.cast_hexagram` derives one personalized
per-line digest. Both functions are unchanged by this ADR.

Both objects are committed in one transaction, before context building and
before any provider is constructed. There is no state in which one exists and
the other does not. Production code still never passes a non-default
`os_random`.

### 6. Stillness is an answer

`(3/4)^6` = 17.8% of casts have no changing line; 35.6% have exactly one; the
mean is 1.5. The contract reads an unchanging hexagram as a settled ground with
the figure standing in it — never as a missing section to pad, and never as a
weaker consultation.

### 7. Legacy consultations are read-only history

Existing `oracle-v1` and `iching-v1` records stay readable in the archive
forever. They can never be retried, resumed, or regenerated: their storage
modules keep their readers and have lost their writers, and the service layer
refuses to advance a legacy row. `oracle_consultations` and
`iching_consultations` are neither altered nor dropped.

Because nothing can generate with them, `ORACLE_SYSTEM_PROMPT` (`oracle-v1`)
and `ICHING_SYSTEM_PROMPT` (`iching-v1`) are retired. The version strings
survive only as values on stored rows, which display fine without the prompt
text.

## Consequences

- One question, one turn of the wheel, one card and one cast, one reading that
  reads the figure in its ground.
- The volume asymmetry is real and must be managed: a Judgment, an Image, up to
  six line texts, and a resulting hexagram is several times the text of a
  card's correspondence block, and a small local model will follow the longest,
  most concrete block regardless of role instructions. `oracle-v2` counters it
  by requiring `alignment_title` to come from the card and the esoteric body to
  name both objects, and by keeping the card's retrieved Book of Thoth
  passages. If context proves too tight, the *retrieval* budget is what gets
  trimmed — never a committed line text, which would be Syzygy making an
  unsourced significance judgment about the oracle's own words.
- `OracleResult` gains no new field. The movement axis lives inside the
  bodies; a dedicated per-object field would invite two mini-readings glued
  together.
- Yarrow-stalk casting, a second card, reversals, a hexagram/card
  correspondence table, transits returning to the Oracle in any form, and
  horary all remain out of scope.
