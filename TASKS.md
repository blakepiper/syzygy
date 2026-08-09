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

## Completed history (M0–M16)

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

## M17 — The ritual you can actually see and drive

### Outcome

Every launch opens with the startup sequence, screens transition instead of
cutting, the mascot appears beyond first launch, the highlighted row in a list
is unmistakable, arrow keys move between the controls of any menu, and the card
sits centred inside its frame.

This milestone is *observed* behaviour, not new subsystems. M14 built the
animation layer and M12 bundled the brand art; the defects below are all
"built, but unreachable on the path a returning user takes".

### M17.1 — Startup runs on every launch, not only first launch

Root cause: `SyzygyApp.on_mount` (`tui/app.py`) routes straight to `home` or
`profile_select` when profiles exist, and `Animations.startup` is only ever
called from `WelcomeScreen.on_mount` (`tui/screens/welcome.py`). A user with a
saved profile therefore never sees the wordmark, the logo, the mascot, or a
single frame of the startup choreography — the app "unceremoniously sends me to
the profile selection screen".

- [ ] M17.1a Add `tui/screens/startup.py` owning the opening sequence: the
      glyph-morph mark, the logo reveal, the mascot, and the routing decision.
      `SyzygyApp.on_mount` pushes `startup` unconditionally; the profile-count
      routing (`none → welcome`, `one → home`, `many → profile_select`) moves
      into the startup screen's completion callback and stays in exactly one
      place. `WelcomeScreen` keeps its first-launch copy and its `[N]`/`[M]`
      keys but stops owning startup.
- [ ] M17.1b Budget the sequence: about 1.4 s at `full`, about 0.5 s at
      `reduced`, and zero frames at `off` (route immediately). Any keypress
      finishes it and routes at once — reuse the existing `finish_all` escape
      hatch in `welcome.py` rather than inventing a second one. Never gate a
      returning user behind an animation they cannot skip.
- [ ] M17.1c Keep `SyzygyApp.startup_seen` meaningful: it suppresses a *second*
      startup within one process (e.g. after profile deletion routes back
      through `welcome`), not the first one of a launch.
- [ ] M17.1d Tests: pilot launches with 0, 1, and 2+ profiles all pass through
      the startup screen and land on the same destination as today; motion
      `off` lands there with no animation handle created; a keypress mid-sequence
      lands there immediately; the too-small gate still wins over startup.

### M17.2 — Transitions and screen entry are actually perceptible

Root cause is two-part. Coverage: only `wheel.py` calls
`animations.trigger("enter", …)` on mount, so most screens simply appear.
Perceptibility: the primitives that do run are short and low-amplitude
(`pulse` 0.10–0.24 s, `reveal` 0.15–0.28 s opacity), which in a terminal at
`FRAME_INTERVAL` is a handful of frames — easy to miss entirely.

- [ ] M17.2a Move screen entry into `SyzygyScreen` (`tui/screens/base.py`) so
      every screen animates in by default: a staggered reveal of the screen's
      top-level regions plus a decode/typewriter pass on the title bar. Give a
      screen a way to opt out or supply its own choreography (`reveal.py` and
      `wheel.py` already have theirs) rather than double-animating.
- [ ] M17.2b Add screen *exit* and cross-screen transition to the same place,
      driven through `SemanticEvent.EXIT`, so `push_screen`/`switch_screen`
      reads as a move rather than a cut. Do not block navigation on the
      animation: the transition runs, the screen switches, and a dropped frame
      never strands the user.
- [ ] M17.2c Perceptibility pass over `animation/primitives.py` and the
      durations in `animation/events.py`. Raise entry durations to a range a
      person notices (roughly 0.35–0.6 s at `full`), and prefer effects that
      survive terminals with poor opacity blending — staged text/glyph reveal
      and colour ramps over opacity alone. Verify the default motion level in
      `animation/motion.py` is `full` for a fresh install and that
      `resolve_motion` is not silently reading a stale/absent settings section.
- [ ] M17.2d Verify the pump: `Animator.on_active`/`on_idle` starts and pauses
      a `set_interval` timer in `app.py`. Add a test that a queued step
      actually advances frames under a real (test-driven) clock, so "no
      animation at all" can never again be a silent scheduling failure.
- [ ] M17.2e Add `syzygy dev animate` (gated on `SYZYGY_DEV`, alongside the
      existing `syzygy.dev` affordances): a demo screen that plays every
      semantic event and every named choreography on demand, at the current
      motion level. This is the manual check that motion is visible on a real
      terminal, which no headless pilot test can make.
- [ ] M17.2f Tests: every screen registers an entry animation on mount; each
      choreography is reachable from the screen that owns it; `reduced` and
      `off` degrade as M14 specifies; no test asserts wall-clock timing.

### M17.3 — The mascot appears past the first launch

Root cause: `Mascot` is constructed in exactly one place, `welcome.py:41`, a
screen a returning user never sees.

- [ ] M17.3a Place the mascot on the startup screen (M17.1) and as a companion
      on `home` at `-wide`/`-tall`, where there are columns to spare. It must
      never displace the SELF/COSMOS/CHANCE triad or push a control below the
      fold at any tier — `tests/tui/test_layout.py` is the arbiter.
- [ ] M17.3b Give it two or three reactive states tied to existing semantic
      events (waiting, drawing, reading complete) rather than a new animation
      vocabulary. Reuse `widgets/brand.py` and `widgets/pixel_art.py`; add no
      new asset without recording it in `docs/BRAND_ASSETS.md`.
- [ ] M17.3c Tests: mascot present at the tiers that allow it and absent at
      `-compact`; layout assertions unchanged; a missing/undecodable asset
      degrades to nothing, never to a traceback (the `SilentTheme` precedent).

### M17.4 — The highlighted row is unmistakable

Root cause: `ListItem.--highlight` in `syzygy.tcss` sets
`background: $syz-panel; color: $syz-accent` over an `ListItem` background of
`$syz-field` — two neighbouring dark greys. On the profile-select list this is
"too subtle to see".

- [ ] M17.4a Restyle selection as a reversal, not a tint: accent background,
      panel-dark text, bold, plus a leading marker glyph (`▍` or `▸`) so the
      highlight survives monochrome terminals and colour-blind viewing. Change
      `tui/palette.py` and `syzygy.tcss` together — a test keeps them in step.
- [ ] M17.4b Apply the same treatment to every list in the app
      (`profile_select`, `archive`, the model list in `local_setup`, any list
      the Oracle adds in M19) and to the focused `Button`, so "where am I" has
      one answer everywhere.
- [ ] M17.4c Tests: the highlight rule is asserted as a contrast/inversion
      relationship between named palette entries rather than as a hard-coded
      hex pair, so a future palette change cannot quietly reintroduce a
      two-greys highlight.

### M17.5 — Keyboard drives every menu

Root cause: nothing in `tui/screens/` handles arrow keys for focus. Textual
moves focus on `tab`/`shift+tab` only, so any row of `Button`s — the
delete-confirmation pair in `profile_select.py`, the eight buttons in
`model_setup.py`, the three in `local_setup.py`, `profile_create.py`, `home.py`
— is mouse- or tab-only, exactly as reported.

- [ ] M17.5a Implement directional focus once in `SyzygyScreen`: `up`/`left`
      move to the previous focusable control, `down`/`right` to the next,
      `enter` activates, `escape` cancels/backs out. Scope movement to the
      focused control's container so a horizontal button row and a vertical
      form both behave the way they look.
- [ ] M17.5b Do not steal keys from widgets that legitimately consume them:
      `Input` (cursor movement), `ListView` (its own up/down), the wheel's
      impulse keys, and any scrollable reading pane. The base handler must run
      only when the focused widget did not handle the key.
- [ ] M17.5c Audit every screen for a reachable, ordered focus chain: a control
      that can be clicked must be reachable by keyboard, in the order it is
      read, with a visible focus indicator (M17.4a). Fix the ordering at the
      composition site rather than with per-screen key handlers.
- [ ] M17.5d Tests: a pilot test per screen that navigates with arrows and
      activates with `enter` only — no mouse events, no `tab` — and reaches
      each control; plus regression tests that `Input` and `ListView` keep
      their own arrow behaviour.

### M17.6 — The card is centred in its frame

Root cause: `TarotCardWidget._content()` returns
`Group(pixels, Text(""), text)`. The tcss on `TarotCardWidget` sets
`content-align: center middle; text-align: center`, but those do not centre the
rows *inside* a composite Rich `Group` — the half-block art renders at its own
width from the left edge of the content box, so a card narrower than the frame
sits left while its caption looks centred.

- [ ] M17.6a Centre inside the renderable: wrap the pixel-art renderable in an
      explicit centring container (`rich.align.Align.center`) and build the
      caption `Text` with `justify="center"`, so alignment does not depend on
      Textual style inheritance through a `Group`.
- [ ] M17.6b Check the same defect at the other art sites — `#reading-card`,
      the reveal screen, and any brand art rendered through
      `widgets/pixel_art.py` — and fix them the same way rather than
      per-screen.
- [ ] M17.6c Tests: render the widget at several widths (including widths where
      the art is narrower than the frame, and the text-only fallback) and
      assert the leading and trailing padding of the art rows differ by at most
      one cell; assert the card's words remain centred; keep the existing
      `art_size_for` fallback behaviour intact.

### Definition of done (M17)

- [ ] Launching with an existing profile plays the startup sequence, shows the
      logo and mascot, and then routes — and any keypress skips it.
- [ ] Moving between screens is a visible transition at `full`, a shortened one
      at `reduced`, and an instant cut at `off`.
- [ ] The highlighted list row is legible at a glance on a monochrome terminal.
- [ ] Every menu in the app is completable with arrows and `enter` alone.
- [ ] The card art is centred in its frame at every layout tier.
- [ ] `pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and
      `syzygy doctor` pass.

---

## M18 — Source material reaches the reading, or says exactly why not

### Outcome

"No source chunks were supplied to the model" stops being an unexplained
dead end. A reading either carries real passages, or tells the user why it
cannot and how to fix it — and either way, the `[I]` inputs view shows the
citations that retrieval actually found.

### Why this happens (read before planning a fix)

This is working as designed, and the design is a licensing constraint, not a
bug. Per ADR 0003, the index shipped in `src/syzygy/resources/knowledge/` is
citations plus non-invertible vectors — **the passages are deliberately not
distributable**. `reading_service._select_knowledge_chunks` therefore drops
every chunk with `has_text == False`, because a citation rendered under the
prompt's `SOURCE PASSAGES` heading invites the model to invent what the page
says. On an install where the user has not run `syzygy knowledge ingest`
against their own PDF copies, there are no passages to supply, and the message
is literally true.

So the fix is not "always send the chunks" — that would either ship the books
or feed the model empty citations. The fix is three things: tell the user the
truth in the place they asked the question, show them the citations (which
*are* shippable and *are* useful to a human), and make ingestion a route rather
than a documented CLI incantation.

**Invariant that must survive this milestone:** citation-only chunks reach the
*user*, never a *provider*. `_select_knowledge_chunks`' filter stays.

- [ ] M18.1a Persist what retrieval found, separately from what the provider
      was given. Add the retrieved citations to the `Reading` (new column via
      an append-only migration, never an edit to a merged one), *not* to
      `InterpretationContext` — that type is the provider's entire input
      surface per `AGENTS.md`, and citations must not enter it. Record per
      citation: source id and tier, title, page range, chunk id, retrieval
      method, and whether its text was available.
- [ ] M18.1b Rewrite the `SOURCE MATERIAL` block in
      `widgets/reading_panel.py` (currently `reading_panel.py:115-125`) into
      two labelled lists: **Passages sent to the model** (what
      `context.knowledge_chunks` holds) and **Where this card is discussed**
      (the citations from M18.1a, always populated). When the first list is
      empty, state the reason in one plain sentence — the source books are not
      redistributable, so Syzygy ships the references but not the text — and
      name the action that changes it.
- [ ] M18.1c Make ingestion reachable from the interface. Add a source-material
      screen (or a section of the existing model-setup route) that reports
      which of the three sources are ingested, explains that the user supplies
      their own copies, shows the expected filenames/locations from
      `docs/KNOWLEDGE_SOURCES.md`, and runs ingestion in a Textual worker with
      progress. It must never download a book, and must refuse a file whose
      hash does not match a known source rather than ingesting something
      arbitrary.
- [ ] M18.1d Surface the state before the reading, not only after it: home
      shows a one-line, dismissible note when no source text is ingested, and
      `syzygy doctor` distinguishes "citations only (normal)" from "ingestion
      present but broken". A citation-only install is not a failing
      environment.
- [ ] M18.1e Prove retrieval never comes back empty. Add a test that
      `retrieve_for_card` returns at least one Tier 0 citation for each of the
      78 card ids against the shipped artifact, so the "where this card is
      discussed" list is always populated even on a bare install.
- [ ] M18.1f With text ingested, confirm the passages actually flow end to end:
      a test asserting `MAX_KNOWLEDGE_CHUNKS_PER_SOURCE` per-source capping,
      Tier 0 ordering first, that the prompt's `SOURCE PASSAGES` section is
      populated, and that the `[I]` view's two lists agree with what the prompt
      contained.
- [ ] M18.1g Update `docs/KNOWLEDGE_SOURCES.md` and the README with the
      user-facing version of this: what ships, what does not, what ingesting
      your own copies changes about a reading, and that a reading without
      passages is still a real reading grounded in `thoth_deck.yaml`.

### Definition of done (M18)

- [ ] `[I]` on any reading shows the citations retrieval found, whether or not
      passages were sent.
- [ ] A citation-only install explains itself in one sentence and offers a
      route to ingestion.
- [ ] No citation-only chunk can reach a provider; the filter and its test
      remain.
- [ ] `pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and
      `syzygy doctor` pass.

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
      from M18.1b). Keep domain logic out of the screens.
- [ ] M19.4c Failure preserves the rite: an interpretation failure keeps the
      committed card and question, shows the fixed alignment, and offers retry
      / fixture / provider recovery — never a redraw. Reuse the existing
      `INTERPRETATION_FAILED` copy and recovery affordances.
- [ ] M19.4d Extend the archive to list consultations alongside readings,
      distinguishable at a glance, reopenable read-only. Keep it list-only, as
      M8 established.
- [ ] M19.4e Layout tiers and motion: the flow works at `-compact` through
      `-tall`, essential controls stay above the fold, focus order is
      keyboard-only navigable (M17.5), and animation degrades with the motion
      level. Add the screens to `tests/tui/test_layout.py`.

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

The I Ching is three thousand years old and belongs to nobody. Legge (1882) is
public domain and complete — judgments, images, and line texts — and is the
working source unless something better turns up. Use it and move on. (Wilhelm/
Baynes is the translation people quote and it is still in copyright, so simply
don't reach for it; that is the whole of the licensing consideration here.)

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
      Legge with a citation per entry. Sourced and cited, never from model
      memory — that rule is about accuracy, not permission, and it applies at
      full strength to a public-domain text.
- [ ] M20.3 Cast mechanics reusing `EntropyCollector` and rejection sampling —
      never `random.random()`, never modulo over a raw byte — with tests
      asserting the chosen method's exact line probabilities over a large
      seeded sample.
- [ ] M20.4 Prompt contract, TUI mode, storage, and archive treatment mirroring
      M19's, with its own prompt version.
