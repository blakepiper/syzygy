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
