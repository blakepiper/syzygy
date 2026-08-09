# Syzygy — Task Checklist

This is the ordered implementation plan for current work. Check off each item
(`- [ ]` → `- [x]`) as it lands and leave a short note for any deliberate
deviation. `docs/old/IMPLEMENTATION_PLAN.md` is the detailed history for M0–M9;
completed work after that is summarized here rather than retained as hundreds
of closed checklist items.

Read `AGENTS.md` before touching code. Nothing below relaxes a product
invariant: a model interprets a card, a cast, and astrology facts already fixed
by Syzygy; it never calculates astrology, selects a card or hexagram, causes a
reroll, or reads application state outside `InterpretationContext`. That holds
for the Oracle exactly as it holds for the daily reading.

## Completed history (M0–M20)

All milestones in this section are complete except where the note says
otherwise.

| Milestone | Shipped outcome |
|---|---|
| M0 | AGPL-3.0 Python package, CLI, development tooling, and release skeleton. |
| M1 | Pure domain contracts and the source-grounded canonical 78-card upright Thoth deck. |
| M2 | Kerykeion behind `AstrologyEngine`, Syzygy-owned transit policy, and deterministic aspect ranking. |
| M3 | OS-backed, interaction-mixed, rejection-sampled sortes draw with equal probability across all 78 cards. |
| M4 | SQLite migrations, repositories, the daily-reading state machine, immediate draw commitment, and database-enforced one-reading-per-profile/date uniqueness. |
| M5 | Complete Textual ritual from welcome/profile through Wheel, reveal, interpretation, and reading. |
| M6 | Multi-source knowledge ingestion and retrieval with the Book of Thoth as the sole canonical source. |
| M7 | Versioned prompts, context builder, structured-output repair path, fixture/llama.cpp/OpenAI/Anthropic providers, keyring storage, and persisted provider selection with safe fixture fallback. |
| M8 | List-only reading archive and reopening of committed readings without rerolling. |
| M9 | CLI/doctor/developer commands, packaging, documentation, and release polish. |
| M10 | Birthplace geocoding, global ritual key fixes, retry recovery, in-TUI provider selection, and bundled card artwork. |
| M11 | Profile-form and deletion fixes, functional llama.cpp endpoint selection, retry recovery, correctly proportioned card art, and a development-only reroll. |
| M12 | Central white-accent palette, bundled logo/mascot, larger wheel glyphs, and compact/standard/wide/tall layout behavior. The proposed Cinzel treatment was deliberately dropped: a terminal cannot change its font and rasterized display text had too little useful reach. |
| M13 | Today's full ranked cosmos, cached LLM summaries for natal chart and cosmos, and the shipped citation-plus-non-invertible-vector knowledge artifact with no source text. |
| M14 | Semantic, tier-aware animation system; startup, SELF, Wheel, reveal, and reading choreography; reduced/off motion preferences; and deterministic animation tests. |
| M15 | Bundled looping theme, global mute and persisted preference, clean shutdown, and failure-safe `SilentTheme`. Audio and birthplace geocoding are included in the main install; their former extras remain compatibility aliases. |
| M16 | Guided local-model setup end to end: machine inventory and conservative fit estimation, a pinned publisher-owned model catalog and llama.cpp runtime manifest, discovery and qualification of an existing server or binary, resumable digest-verified downloads with safe archive extraction, a localhost-only supervisor with typed startup diagnosis, a no-side-effect smoke test gating activation, a resumable TUI wizard, and `syzygy model setup-local` / `model local status\|doctor\|list\|start\|stop\|remove`. Catalog entries ship `provisional`: the evaluation harness exists and is runnable but has not been run against them, and the UI says so. Carried open below: M16.10f. |
| M17 | Startup on every launch rather than only the first, default entry/exit transitions on every screen, the mascot past first launch, an unmistakable list highlight, arrow-key navigation through every menu, and centred card art. Four deliberate departures, all reasoned where a reader will hit them: entry durations exceed `docs/animation.md` section 5's figures (five frames is not a transition — see `animation/events.py`'s module docstring); directional focus is *bindings*, not an `on_key` handler, so `Input` and `ListView` keep their own arrows; no global `escape`, because the too-small gate must not be dismissable; and `timeline.Sequence.finish` had a real float-accumulation bug that silently dropped a sequence's trailing `Call`, fixed here. |
| M18 | Source material reaches the reading or says exactly why not. Retrieval's citations are persisted on the `Reading` (migration 6), separately from `InterpretationContext` — the textless filter is untouched, so citations reach the user and passages reach the provider. `[I]` shows both lists; `[K]` opens a source-material screen that reports every source's state, ingests a PDF you already have on a worker with progress, never downloads a book, and refuses a file that is not the edition the shipped citations describe; home carries a one-line dismissible note; and `doctor`/`knowledge status` separate "citations only (normal)" from "broken". All 78 cards are proven to carry a Tier 0 citation against the artifact that actually ships. |
| M19 | The Oracle: a question-led rite separate from the daily card, recorded in ADR 0006. Its own table (migration 7 — M18 had already taken 6), repository, service, and `ASKED → DRAWN → CONTEXT_READY → INTERPRETING → COMPLETE/INTERPRETATION_FAILED` state machine, with no per-date uniqueness and no reroll within a consultation. The question's keystroke timing feeds the same `EntropyCollector` the wheel uses; the text itself is capped, normalized, stored as typed, and JSON-quoted beneath the fixed facts as data that cannot alter the card, the astrology, or the output contract. `oracle-v1` and `OracleResult` add a question-facing response to the two registers; all four providers get it through the shared structured-output path, `FixtureProvider` included, so the rite completes with no model configured. TUI ask → Wheel (Oracle mode, handing the fixed draw straight to the result screen; the staged daily `RevealScreen` is untouched) → result, plus archive listing and `syzygy oracle ask/list/show`. No horary: it needs current location and momentary angles, which `AGENTS.md` forbids outright, so ADR 0006 records it out of scope rather than deferred. Follow-ups shipped alongside: the mascot as Braille line art in one centered lockup, and natal summaries moved onto the saved `Profile` (migration 8) so restarts reuse them. |
| M20 | I Ching as a mutually exclusive Oracle mode, recorded in ADR 0007: the three-coin method (so a moving yang is 1/8, not the yarrow stalks' 1/16), changing lines and the resulting hexagram treated as one cast's direction, never a second oracle competing with the card. `iching_legge.yaml` carries all 64 judgments, Images, and line texts transcribed and page-cited from Legge (1882); casting reuses `EntropyCollector` and rejection sampling, with the exact line probabilities asserted over a large seeded sample. Migration 9, an `iching-v1` prompt, its own TUI mode and archive treatment, and `oracle ask --mode iching`; Thoth remains the default. Follow-ups shipped alongside: bare `syzygy knowledge ingest` preflights and ingests all three canonical PDFs in one run, and `[D]` on the archive confirms before deleting any entry, with daily deletion leaving a database-enforced profile/date tombstone so it can never become a reroll. |

Historical implementation details remain discoverable in git. Do not expand
this section back into a task-by-task ledger.

### Carried open from a completed milestone

- [ ] **M16.10f — manual clean-machine matrix.** Linux x86-64 CPU was
      performed end to end on real hardware and recorded in
      `docs/LOCAL_MODEL_MAINTENANCE.md` (llama.cpp b10331 downloaded and
      digest-verified, unpacked, qualified; Qwen3-4B Q4_K_M downloaded and
      digest-verified; server started on `127.0.0.1`; smoke test passed all
      three schemas at 93.2 s / 49.8 s / 37.7 s). Still unrun on real
      hardware: macOS Apple Silicon, Windows x86-64 (CPU and NVIDIA), Linux
      x86-64 NVIDIA, plus a manual pass over the advanced external-server
      route and the unsupported-platform handoff (both covered by tests
      only). Record exact runtime/catalog versions and observed peak
      memory/time, with no personal machine identifiers. Blocks nothing
      below; it blocks calling the local-model path validated on those
      platforms.

---

## M21 — Liber Syzygy

Independent of M17–M20; it can be written at any point. Nothing depends on it
and it depends on nothing.

### Outcome

One text — `docs/liber_syzygy.md` — that states what Syzygy is *for*. Not a
README, not a design doc, not marketing. A composed work in the register of a
grimoire, a Thelemic *Liber*, and a Tibetan *terma*, which a person could read
once and understand why the application exists.

**Keep it out of git until the author says otherwise.** `docs/liber_syzygy.md`
is gitignored. Write it, iterate on it locally, and do not commit it, quote it
into the README, or render it into the TUI until that changes.

### The argument the text must carry

These are the author's beats, not a suggestion of them. The order is open; the
content is not.

1. **The modern world is missing an oracle.** Ancient societies had them, and
   consulting them was not superstition at the margins — the founding and
   preservation of oracles was a first question of life and of statecraft. That
   institution is gone and nothing replaced it.
2. **The modern person is cut off** from the spiritual world and from the great
   mystery that reveals itself through time, synchronicity, and chance.
3. **The tripartite paradigm: SELF, COSMOS, CHANCE.** The same triad the
   application is built on — the natal chart you were given, the sky as it
   stands today, and the one card that no one chose. The text should make the
   reader feel why it takes all three, and why two of them are not enough.
4. **The channel is number, randomness, and intention.** Pythagorean: number as
   the substance of things rather than a description of them. Randomness is not
   noise but the surface through which the mystery is legible. Intention is
   what makes a draw a question rather than an accident.
5. **The gods do not control fate; they reveal its workings.** From the author's
   inspiration excerpt: *"The true gods have a kind of power, but not the kind
   the many imagine. Why should they care for mankind? They are rare and
   precious, and it is for man to find, acknowledge, and honor them. This, at
   least, was the ancient view: and the foundation and preservation of oracles
   was the first question of life and also of statecraft. Gods could not control
   nature or fate, but could reveal its workings at key times."* This is
   inspiration for the register and the theology, not necessarily material to
   quote.

### Form

- [x] M21.1 Settle the form before drafting. Recommendation: short numbered
      chapters of numbered verses (the *Liber* convention), so any line can be
      cited as `II:7` — which is also what makes the text usable later in the
      interface, an epigraph at a time. Terma supplies the framing device (a
      text recovered rather than composed, with a colophon); grimoire supplies
      the operative sections — what the instrument is, how it is approached,
      what is asked of the one who turns it.
- [x] M21.2 Draft it. Aim for a text that is short enough to read in one
      sitting and dense enough to reward a second — on the order of 800–1500
      words, not a book. Every verse earns its place; nothing is there to make
      the document feel long. Archaic register is welcome; archaic *padding* is
      not.
- [x] M21.3 Keep it true to the instrument it describes. The text may not
      promise mechanics Syzygy does not have: upright cards only, one card,
      one canonical reading per day, the wheel turned by the querent's own
      motion, the card fixed before it is interpreted and never redrawn. Where
      the text is deliberately grander than the code, it should be grander in
      register, never in claim.
- [x] M21.4 Attribution discipline. The work is Syzygy's own composition; the
      recovered-text conceit is a literary device and that is fine. But any
      line presented as a quotation from a real source must actually be one,
      correctly attributed — including the author's excerpt above, whose source
      needs identifying before it can be quoted in the text with a citation.
      Invent no scripture, no lineage, and no scholar.
- [x] M21.5 Decide the register question explicitly and write the answer into
      the text's own colophon: does *Liber Syzygy* speak in Syzygy's two voices
      (esoteric and conventional), or only the esoteric one? Recommendation:
      only the esoteric — the conventional register exists to translate a
      reading for a person, and a founding text is not a reading.

### Not in scope

Placing the text in the application — a `[?]` reading screen, an epigraph on
the startup sequence, a verse on the reveal, README material, or anything that
would feed it to a model as tone guidance. Those become their own task once the
author has decided the text is good and it comes out of `.gitignore`.

### Implementation note (M21)

Written to `docs/liber_syzygy.md`, still gitignored and uncommitted, referenced
nowhere in the README, the TUI, or any prompt. Seven chapters of numbered
verses (`II:7`), 1,422 words before the colophon, taking the recommendation on
form and on register: the text speaks only in the esoteric voice, and the
colophon says why — the conventional register translates a reading for a
person, and the ground a reading is given under is not itself a reading.

Two calls worth knowing about:

- **The excerpt is not quoted.** Its source could not be established — searches
  for its distinctive phrases return nothing matching, only unrelated material
  on Greek fate and oracles. Under M21.4 that leaves exactly one honest option,
  so the theology was rewritten in the book's own voice (chapter IV) and the
  colophon states plainly that the passage shaped the register, was not
  reproduced, and is not attributed. If the author knows the source, IV can
  carry a real citation instead.
- **The terma framing is disclosed rather than sustained.** The book presents
  itself as recovered, and the colophon's first line says it is not. Keeping
  the conceit unbroken would have meant an artefact that reads as a fabricated
  lineage the moment it leaves the author's machine, which M21.4 forbids more
  than it forbids inventing a scholar by name.

Chapter V is the accuracy load-bearing one: one upright card, one card per day
and no better morning, the lot written down before the interpreter is summoned
and unchanged across a retry, birthplace asked and current location never,
every Oracle asking its own turn of the wheel, one chance object per question,
and the record kept locally as the reading actually given.

Note: V:11 and VII:2 are written against the one-chance-object rule that M22
replaces. The text is not committed and the author has said it will be edited;
M22.5e carries the correction so it is not forgotten. As of M22 the file is
no longer in the working tree at all — see M22.5e.

---

## M22 — The Oracle as figure and ground

Independent of M21. It changes the Oracle only: the daily reading's card,
uniqueness, transits, prompt, and storage are untouched by every task below.

### Outcome

There is one Oracle rite and no mode to choose. Every consultation carries both
chance objects — one upright Thoth card and one six-line I Ching cast — from a
single turn of the wheel, with roles fixed by the instrument:

| Object | Role |
|---|---|
| Hexagram Judgment (+ trigrams) | **the ground** — the character of the time the question is asked in |
| The Thoth card | **the figure** — the specific thing the oracle puts in front of the querent |
| Changing lines, resulting hexagram | where the ground is unstable, and its direction |
| The Image | conduct — how to bear oneself in it |

Today's transits leave the Oracle entirely. The natal chart stays.

### What this supersedes

- **ADR 0007's "alternative Oracle mode" decision.** A consultation now
  contains exactly two chance objects with disjoint roles, not one of two.
  Everything else in 0007 stands unchanged: the three-coin method and its
  probabilities, changing lines, the resulting hexagram as direction, and the
  Legge (1882) resource with page citations.
- **ADR 0006 section 2, for the Oracle only.** SELF remains; COSMOS does not.

### ADR 0008 — decisions to record before writing code

1. **One rite, two chance objects, disjoint roles.** The roles above are fixed
   by Syzygy in the prompt contract. The model is never asked which object
   governs, and never asked to reconcile them.
2. **Why figure and ground rather than a topical split.** A figure and its
   ground cannot contradict each other; they can only qualify each other. The
   Tower in a time of Waiting reads differently from the Tower in a time of
   Great Vigour, and no arbiter is needed for that. This is what dissolves
   0007's two-competing-oracles objection — structurally, not by instructing
   the model to be careful. Record the rejected alternatives with their
   reasons: *what it is / where it goes* (the cast's role goes empty on the
   17.8% of casts with no changing lines); *inner/outer* (redundant — a
   hexagram already encodes inner and outer in its lower and upper trigrams);
   *roles varying by question type* (requires classifying the question, and
   only the model could classify it — the same reason horary is out); and
   *leaving the tension unresolved as information* (produces
   on-one-hand/on-the-other prose, the failure mode this design exists to
   avoid).
3. **No correspondence between the 64 and the 78 is used, and none may be
   invented.** There is no canonical mapping — the counts do not divide, the
   published attempts are contested, and Crowley practising both systems is
   biography, not a table. Resolution of the two objects is structural only.
   Note for the record that no such table exists anywhere in this repository:
   it was considered in design discussion and rejected, never built, so there
   is nothing to remove.
4. **Transits leave the Oracle.** A question is usually about a horizon a
   transit is not on, and a Moon aspect exact for four hours will be woven in
   earnest into an answer about a decision six months out, with nothing in the
   text telling the reader it will be gone by dinner. That is an accuracy
   defect, not a matter of taste. The natal chart is retained: it is the member
   of the trio the card can actually speak to, since both use decans, planets,
   signs, and elements while a hexagram has no astrological hook at all. The
   daily rite keeps its transits, because a daily reading *is* about today.
   Horary stays out of scope for its original reason — it needs current
   location and momentary angles, which `AGENTS.md` forbids.
5. **One entropy collection, two derivations.** The question's keystrokes and
   one turn of the wheel feed a single `EntropyCollector`; the card draw and
   each of the six lines come from domain-separated derivations of it. Both
   objects are committed in one transaction before context building or any
   provider call. Production code still never passes a non-default `os_random`.
6. **Stillness is an answer.** `(3/4)^6` = 17.8% of casts have no changing
   line; 35.6% have exactly one; the mean is 1.5. The contract must read an
   unchanging hexagram as a settled ground with the figure standing in it,
   never as a missing section to pad.
7. **Legacy consultations are read-only history.** Existing `oracle-v1` and
   `iching-v1` records stay readable in the archive forever and can never be
   retried, resumed, or regenerated.

### M22.1 — Domain and storage

- [x] M22.1a Add the combined consultation to `syzygy/domain/` — question,
      card draw, and cast in one aggregate, reusing `TarotDraw` and the
      existing cast type unchanged. Both objects are **non-nullable** once the
      status is past `ASKED`, so a one-object consultation is not
      representable. Reuse the `ASKED → DRAWN → CONTEXT_READY → INTERPRETING →
      COMPLETE / INTERPRETATION_FAILED` shape and its `ALLOWED_TRANSITIONS`.
- [x] M22.1b Migration **11** (append-only; 10 is archive deletion) creating
      the combined table: the columns `oracle_consultations` has, minus
      `transit_snapshot_json`, plus the cast columns. Index by
      `(profile_id, asked_at_utc DESC)`. No per-date uniqueness. Do not alter
      or drop `oracle_consultations` or `iching_consultations`.
- [x] M22.1c Repository and service modelled on the existing pair, committing
      both objects before any provider call and resumable from status alone.
- [x] M22.1d Demote `storage/oracle.py` and `storage/iching.py` to read-only
      archive sources: keep their readers, remove or disable their write and
      retry paths, and make the service layer refuse to advance a legacy row.
- [x] M22.1e Tests: every illegal transition rejected; a consultation with one
      object absent cannot be constructed or stored; retry after a failed
      interpretation reuses *both* committed objects; a crash between draw and
      interpretation resumes without redrawing or recasting; legacy rows read
      but never write; nothing touches `readings`.

### M22.2 — One turn, two objects

- [x] M22.2a Draw the card and cast the six lines from one `EntropyCollector`
      seeded by the question's keystrokes and the wheel, with distinct domain
      separation per object and per line. Reuse `sortes.draw.draw_card` and the
      existing cast function unchanged — all 78 cards equiprobable, rejection
      sampled, no `random.random()` and no modulo over a raw byte.
- [x] M22.2b Commit both in a single transaction. There is no state in which
      one exists and the other does not.
- [x] M22.2c Tests: one collector serves both; the card distribution and the
      per-line probabilities are unchanged from M3 and M20 over a large seeded
      sample; the two derivations are independent; both objects are on disk
      before any provider is constructed.

### M22.3 — Prompt contract (`oracle-v2`)

- [x] M22.3a Add `ORACLE_PROMPT_VERSION = "oracle-v2"` with the roles stated as
      structure, not advice. Block order, which is also the narration order:
      **the ground** (hexagram name, trigrams, Judgment) → **the figure** (card,
      correspondences, retrieved passages) → **movement** (changing-line texts
      and the resulting hexagram, or an explicit statement that nothing is
      moving) → **conduct** (the Image) → SELF (natal anchors) → the question,
      quoted as data that cannot alter any of the above or the output schema.
      No transit block exists in this prompt at all.
- [x] M22.3b Require the reading to land the figure: `alignment_title` comes
      from the card, and the esoteric body must name both the card and the
      hexagram. This is the counterweight to the volume problem — a Judgment,
      an Image, up to six line texts, and a resulting hexagram is several times
      the text of a card's correspondence block, and a 4B or 8B local model
      will follow the longest, most concrete block regardless of what the role
      instructions say.
- [x] M22.3c **Keep the card's retrieved Book of Thoth passages**, under M18's
      rules unchanged (`has_text` filter; citation-only chunks reach the user,
      never a provider). Recommendation, and the default to implement: the
      dropped transit block frees roughly the budget the hexagram consumes, and
      the passages are what keep the figure from being swamped. If a local
      model's context proves too tight, trim the *retrieval* budget — never a
      committed line text. Dropping a line text would be Syzygy making an
      unsourced significance judgment about which of the oracle's own words
      matter, which is exactly what it must not do.
- [x] M22.3d **No new result fields.** Recommendation, and the default to
      implement: `OracleResult` keeps `alignment_title`, the two registers,
      `source_chunk_ids`, and `question_response`; the movement axis lives
      inside the bodies. A dedicated per-object field invites two mini-readings
      glued together, which is the mush this design is meant to prevent. Derive
      the JSON schema the same way the existing contracts do so the
      constraining schema cannot drift from the validating one.
- [x] M22.3e Retire `ORACLE_SYSTEM_PROMPT` (`oracle-v1`) and
      `ICHING_SYSTEM_PROMPT` (`iching-v1`) once nothing can generate with them.
      The version strings survive only as values on stored legacy rows, which
      display fine without the prompt text. This is safe precisely because
      M22.1d made legacy consultations unretryable.
- [x] M22.3f `FixtureProvider` returns a plausible combined consultation so the
      rite completes with no model configured.
- [x] M22.3g Tests: schema derivation; block order and the absence of any
      transit content; a question containing prompt-injection text changes
      neither object nor the schema; the no-changing-lines case renders as a
      settled ground rather than an empty section; the repair path on malformed
      output; provenance recorded on every consultation.

### M22.4 — The TUI

- [x] M22.4a Remove the mode buttons from `oracle_ask.py` — the ask screen is
      question, budget, and framing only. `[O]` goes straight to the wheel.
- [x] M22.4b One result screen replacing `oracle_result.py` and
      `iching_result.py`. **Reveal order is not narration order**: the card is
      revealed first, as the wheel's payoff and the app's visual identity, with
      the six lines building upward beneath it; the prose reads ground-first.
      Both objects are legible at a glance, including whether anything is
      moving. `[I]` keeps M18's two-list inputs treatment plus the question.
- [x] M22.4c Motion: the six lines building bottom-upward under the revealed
      card is the new beat, and it is honest — both objects are committed
      before it plays. It degrades with the motion level like everything else.
- [x] M22.4d Failure preserves the rite: an interpretation failure keeps the
      question, the card, *and* the cast, shows them, and offers retry /
      fixture / provider recovery. Never a redraw and never a recast.
- [x] M22.4e Archive: four record kinds now — daily reading, combined
      consultation, and the two legacy kinds — each distinguishable at a
      glance, all reopenable read-only, legacy kinds visibly historical.
      `[D]` deletion behaviour is unchanged.
- [x] M22.4f Layout tiers `-compact` through `-tall`, keyboard-only focus
      order, essential controls above the fold. Update
      `tests/tui/test_layout.py` for the new screen and the removed ones.

### M22.5 — CLI, docs, and the mental model

- [x] M22.5a `syzygy oracle ask` drops `--mode`. Accept the flag for one
      release with a printed notice that both oracles are now cast together,
      rather than failing on it.
- [x] M22.5b `oracle show` renders both objects and marks legacy records as
      the single-object rite they were.
- [x] M22.5c Update `AGENTS.md`: the one-paragraph mental model still reads
      "one random Thoth card, or one I Ching cast in that Oracle mode", and the
      I Ching invariant still says a provider receives "the committed cast".
      Both describe the superseded design.
- [x] M22.5d README: the Oracle casts both, chooses nothing, and does not use
      the day's transits; the daily reading is unchanged.
- [ ] M22.5e `docs/liber_syzygy.md` V:11 and VII:2 describe one chance object
      per question. Edit them to the new rite. The text stays gitignored.
      **Not done: the file is not in the working tree.** It is gitignored, so
      it was never committed, and the only copy on this machine is in the
      desktop trash — and that copy is a different, earlier draft with no
      chapter or verse numbering, so it is not the M21 text this task points
      at. Restoring something the author deleted is their call, not a coding
      agent's. The correction to carry when the text comes back: an Oracle
      question now receives two chance objects from one turn of the wheel — a
      card as the figure and a cast as the ground — not one.

### Definition of done (M22)

- [x] One question, one turn of the wheel, one card and one cast, one reading
      that reads the figure in its ground.
- [x] No mode choice exists anywhere: TUI, CLI, or storage.
- [x] No Oracle code path reads a transit, and no Oracle prompt contains one.
- [x] Neither object can be redrawn, recast, or separated from the other, and a
      failed interpretation retries against both.
- [x] Legacy consultations remain readable and cannot be advanced.
- [x] The daily reading's behaviour is byte-for-byte unchanged.
- [x] The rite completes with no model configured.
- [x] `pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and
      `syzygy doctor` pass.

### Not in scope

Yarrow-stalk casting, a second card, reversals, a correspondence table between
hexagrams and cards, transits returning to the Oracle in any form, and horary.
