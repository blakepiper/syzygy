# Syzygy — Task Checklist

This is the ordered implementation plan for current work. Check off each item
(`- [ ]` → `- [x]`) as it lands and leave a short note for any deliberate
deviation. `docs/old/IMPLEMENTATION_PLAN.md` is the detailed history for M0–M9;
completed work after that is summarized here rather than retained as hundreds
of closed checklist items.

Read `AGENTS.md` before touching code. Nothing below relaxes a product
invariant: a model interprets a card and astrology facts already fixed by
Syzygy; it never calculates astrology, selects a card, causes a reroll, or
reads application state outside `InterpretationContext`. That holds for the
Oracle in M19 exactly as it holds for the daily reading.

## Completed history (M0–M18)

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

## M19 — The Oracle

### Outcome

`[O]` from home opens a consultation: the user asks a question in their own
words, turns the wheel, receives one Thoth card, and gets an interpretation
that answers *that question* through *that card* — in the same two registers as
the daily reading. It is a distinct rite from the daily card, stored
separately, and it changes none of the daily reading's invariants.

### Architecture decisions to settle first (ADR 0006)

Write the ADR before the code; these are the decisions it must record, with the
recommendation each one starts from.

1. **The Oracle is a separate rite, not a second daily reading.** It gets its
   own table and its own state machine. Reusing `readings` would collide with
   the `UNIQUE (profile_id, consultation_local_date)` constraint that makes the
   daily card canonical, and that constraint is not negotiable.
2. **The Oracle is unlimited in count but not in effort.** Every consultation
   requires its own turn of the wheel and its own draw. There is no reroll
   *within* a consultation — once the card is committed, a failed or retried
   interpretation reuses it, exactly as `ReadingStatus` enforces today. Asking
   again is a new question, visibly a new consultation, never a second opinion
   on the same one.
3. **Astrology's role: SELF and COSMOS as context, demoted below the
   question and the card.** The consultation uses the profile's natal chart and
   the same ranked transits the daily reading uses, so the mental model stays
   SELF + COSMOS + CHANCE. It does **not** cast a horary chart. Horary needs
   the querent's current location and the Ascendant of the moment of asking,
   and `AGENTS.md` forbids current-location astrology outright — that
   invariant governs, so the ADR records horary as out of scope with the
   reason, not as a future maybe.
4. **The question is user text and is treated as such.** Length-capped, stored
   verbatim locally, never logged to a server command line, and sent only to
   the provider the user configured (which may be entirely local after M16).
   Prompt construction must be injection-resistant: the question is quoted
   data inside a fixed contract, never an instruction that can restate the
   card, the astrology, or the output schema.
5. **The interpretation stays divinatory.** The Oracle reflects; it does not
   issue medical, legal, or financial directives, and it does not predict a
   dated event as fact. This belongs in the prompt contract and the schema, not
   in a filter bolted on afterwards.
6. **I Ching is deferred to M20 behind a sourcing review** — see below.

### M19.1 — Domain and storage

- [ ] M19.1a Add `syzygy/domain/oracle.py`: `OracleQuestion` (text, asked-at,
      local date), `OracleConsultation`, `OracleStatus`, and its own
      `ALLOWED_TRANSITIONS`. Mirror `ReadingStatus`' shape
      (`ASKED → DRAWN → CONTEXT_READY → INTERPRETING → COMPLETE /
      INTERPRETATION_FAILED`) so the card-committed-before-any-model-call rule
      is enforced by the same kind of checkable state machine, and so no state
      may return to `ASKED` or `DRAWN` once a card exists.
- [ ] M19.1b Add migration 6 (append-only) creating `oracle_consultations`:
      id, profile id, question text, asked-at UTC, local date, status, card
      draw JSON, transit snapshot JSON, context JSON, result JSON, provider,
      model, prompt version, timestamps. No uniqueness constraint on
      `(profile_id, date)` — many consultations per day is the point. Index by
      `(profile_id, asked_at)` for the archive.
- [ ] M19.1c Add `storage/oracle.py` (repository) and `storage/oracle_service.py`
      (orchestration), modelled on `readings.py` / `reading_service.py`. The
      service commits the draw before any provider call and is resumable from
      status alone, exactly as `draw_todays_reading` is.
- [ ] M19.1d Tests: the state machine rejects every illegal transition; a
      failed interpretation retried reuses the committed card; a crash between
      draw and interpretation resumes without redrawing; consultations do not
      appear in, or interfere with, `readings`.

### M19.2 — Chance, entropy, and the question

- [ ] M19.2a Reuse `sortes.draw.draw_card` and `EntropyCollector` unchanged —
      all 78 cards, equal probability, OS randomness mixed with interaction
      entropy. The Oracle adds no deck, no spread, no orientation.
- [ ] M19.2b Feed the keystrokes of typing the question into the
      `EntropyCollector` as interaction entropy, in addition to the wheel. It
      is the same mechanism the wheel already uses and it makes the asking part
      of the chance rather than a form field before it. Production code still
      never constructs `EntropyCollector` with a non-default `os_random`.
- [ ] M19.2c Cap and normalise the question: a length limit that fits the
      prompt budget, whitespace normalisation, a refusal for empty input, and
      no interpretation of markup or control characters. Store the original
      text as the user typed it.

### M19.3 — Prompt contract and result schema

- [ ] M19.3a Add `ORACLE_PROMPT_VERSION = "oracle-v1"` and an `OracleResult`
      model to `domain/interpretation.py` + `interpretation/prompts.py`,
      deriving its JSON schema the same way `_response_json_schema` does so the
      constraining schema cannot drift from the validating one. Fields: the
      esoteric register, the conventional register, and an explicit
      question-facing response; provenance fields stripped from the
      model-facing schema as today.
- [ ] M19.3b Build the oracle context through a new builder in
      `interpretation/context_builder.py` producing an
      `InterpretationContext` — same input surface, no provider reaching for
      anything else. The question is a context field, not an out-of-band
      instruction.
- [ ] M19.3c Structure the prompt so the fixed facts dominate: the card and its
      correspondences, the ranked transits, the natal placements, the retrieved
      passages (subject to M18's rules), then the question as quoted data with
      an explicit instruction that it may not alter the card, the astrology, or
      the output contract.
- [ ] M19.3d Reuse the shared parse/validate/repair-retry path in
      `interpretation.providers.structured_output`. All four providers get the
      Oracle for free; `FixtureProvider` must return a plausible fixture
      consultation so the rite works with no model configured.
- [ ] M19.3e Tests: schema derivation, register separation, a question
      containing prompt-injection text does not change the fixture's reported
      card or schema, repair path on malformed output, and provenance recorded
      on every consultation.

### M19.4 — The consultation flow in the TUI

- [ ] M19.4a Add `[O] Oracle` to `HomeScreen.BINDINGS` and its key line.
      Available whether or not today's daily reading exists — the Oracle is not
      gated by the daily card and does not consume it.
- [ ] M19.4b Add `tui/screens/oracle_ask.py` (question input, character
      budget, plain-language framing of what will happen) → the existing wheel
      screen in an Oracle mode → `tui/screens/oracle_result.py` (card, answer,
      registers, `[I]` inputs view reusing `reading_panel`'s two-list treatment
      from M18). Keep domain logic out of the screens.
- [ ] M19.4c Failure preserves the rite: an interpretation failure keeps the
      committed card and question, shows the fixed alignment, and offers retry
      / fixture / provider recovery — never a redraw. Reuse the existing
      `INTERPRETATION_FAILED` copy and recovery affordances.
- [ ] M19.4d Extend the archive to list consultations alongside readings,
      distinguishable at a glance, reopenable read-only. Keep it list-only, as
      M8 established.
- [ ] M19.4e Layout tiers and motion: the flow works at `-compact` through
      `-tall`, essential controls stay above the fold, focus order is
      keyboard-only navigable (M17's directional focus), and animation
      degrades with the motion level. Add the screens to
      `tests/tui/test_layout.py`.

### M19.5 — CLI parity and docs

- [ ] M19.5a Add `syzygy oracle ask "<question>"` (draws, interprets, prints
      both registers) and `syzygy oracle list` / `oracle show <id>`. Interactive
      when attached to a terminal; never prompts in CI.
- [ ] M19.5b Document the Oracle in the README and `docs/old/DESIGN.md`'s
      successor notes: what it is, how it differs from the daily reading, that
      it is unlimited but each consultation is its own draw, and where the
      question is stored.

### Definition of done (M19)

- [ ] A user can ask a question, turn the wheel, and receive an interpretation
      that answers it through the drawn card.
- [ ] A consultation never touches, blocks, or is blocked by the daily reading,
      and never redraws its own card.
- [ ] The question cannot alter the card, the astrology, or the output schema.
- [ ] The rite completes with no model configured, via `FixtureProvider`.
- [ ] `pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and
      `syzygy doctor` pass.

---

## M20 — I Ching

Do not start this before M19 ships — it reuses the Oracle's flow, storage, and
prompt shape wholesale. It is listed now because M19's design should not
foreclose it.

Legge (1882) is the working source: complete — judgments, images, and all six
line texts per hexagram — freely available, and already cleanly digitized. Take
it and go.

The genuinely open question is mechanical. Casting six lines is trivial next to
`sortes.draw`, but the three-coin and yarrow-stalk methods produce *different*
probabilities for changing lines — 1/8 vs 1/16 for a moving yang, among others.
That is a real divinatory choice about which tradition Syzygy is practising,
and it belongs in the ADR.

- [ ] M20.1 ADR: cast method and its probability distribution (three-coin vs
      yarrow-stalk), whether changing lines and the resulting second hexagram
      are in scope, and how the hexagram composes with the Thoth card — a
      second chance object in the same consultation, or an alternative mode the
      user selects. Recommendation: an alternative mode, so no consultation
      carries two competing oracles.
- [ ] M20.2 Canonical hexagram data as a resource file with the same grounding
      discipline as `thoth_deck.yaml`: hexagram number, King Wen sequence,
      name, trigrams, judgment, image, and the six line texts, transcribed from
      Legge with a citation per entry. Transcribed and cited, never from model
      memory — the same accuracy rule `thoth_deck.yaml` lives under.
- [ ] M20.3 Cast mechanics reusing `EntropyCollector` and rejection sampling —
      never `random.random()`, never modulo over a raw byte — with tests
      asserting the chosen method's exact line probabilities over a large
      seeded sample.
- [ ] M20.4 Prompt contract, TUI mode, storage, and archive treatment mirroring
      M19's, with its own prompt version.

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

- [ ] M21.1 Settle the form before drafting. Recommendation: short numbered
      chapters of numbered verses (the *Liber* convention), so any line can be
      cited as `II:7` — which is also what makes the text usable later in the
      interface, an epigraph at a time. Terma supplies the framing device (a
      text recovered rather than composed, with a colophon); grimoire supplies
      the operative sections — what the instrument is, how it is approached,
      what is asked of the one who turns it.
- [ ] M21.2 Draft it. Aim for a text that is short enough to read in one
      sitting and dense enough to reward a second — on the order of 800–1500
      words, not a book. Every verse earns its place; nothing is there to make
      the document feel long. Archaic register is welcome; archaic *padding* is
      not.
- [ ] M21.3 Keep it true to the instrument it describes. The text may not
      promise mechanics Syzygy does not have: upright cards only, one card,
      one canonical reading per day, the wheel turned by the querent's own
      motion, the card fixed before it is interpreted and never redrawn. Where
      the text is deliberately grander than the code, it should be grander in
      register, never in claim.
- [ ] M21.4 Attribution discipline. The work is Syzygy's own composition; the
      recovered-text conceit is a literary device and that is fine. But any
      line presented as a quotation from a real source must actually be one,
      correctly attributed — including the author's excerpt above, whose source
      needs identifying before it can be quoted in the text with a citation.
      Invent no scripture, no lineage, and no scholar.
- [ ] M21.5 Decide the register question explicitly and write the answer into
      the text's own colophon: does *Liber Syzygy* speak in Syzygy's two voices
      (esoteric and conventional), or only the esoteric one? Recommendation:
      only the esoteric — the conventional register exists to translate a
      reading for a person, and a founding text is not a reading.

### Not in scope

Placing the text in the application — a `[?]` reading screen, an epigraph on
the startup sequence, a verse on the reveal, README material, or anything that
would feed it to a model as tone guidance. Those become their own task once the
author has decided the text is good and it comes out of `.gitignore`.
