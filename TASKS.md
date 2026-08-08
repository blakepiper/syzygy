# Syzygy — Task Checklist

Ordered, ID'd checklist derived from `IMPLEMENTATION_PLAN.md`. Check off
(`- [ ]` → `- [x]`) as you complete each task, and add a one-line note if
you deviated from the plan. Dependencies are noted inline; unless stated
otherwise, tasks within a milestone are sequential.

**Next recommended task: M7.7** (`providers/llama_cpp.py`), then the two
hosted providers — the prompt contract, the context builder, and the
knowledge base are all wired into `reading_service` now, so the remaining
gap to a v0.1 is an actual model behind the interface. A provider is
transport only: take `prompts.SYSTEM_PROMPT` +
`prompts.build_user_prompt(context)`, constrain output with
`prompts.RESPONSE_JSON_SCHEMA` where the API allows, validate into
`InterpretationResult`, and on failure retry exactly once with
`prompts.build_repair_prompt(...)` before raising.

---

## M0 — Repository skeleton — DONE

- [x] M0.1 `pyproject.toml`: dependencies, entry point, pytest/ruff/mypy config
- [x] M0.2 Package skeleton (`src/syzygy/...`)
- [x] M0.3 `LICENSE` (AGPL-3.0) + `docs/adr/0001-agpl-license-for-kerykeion.md`
- [x] M0.4 `README.md`
- [x] M0.5 `syzygy.cli` entry point with `dev deck` and `doctor` subcommands

## M1 — Domain models and Thoth deck — DONE

- [x] M1.1 Core domain schemas (`src/syzygy/domain/*.py`)
- [x] M1.2 `src/syzygy/resources/thoth_deck.yaml` (78 cards, source-verified)
- [x] M1.3 `src/syzygy/sortes/deck.py` (`load_deck`, `get_card`, validation)
- [x] M1.4 `tests/sortes/test_deck.py` (counts, uniqueness, no-reversal guard,
      two Thoth-specific attribution regression tests)
- [x] M1.5 `docs/THOTH_INGESTION_MAP.md` (PDF structure, for M6)

## M2 — Astrology — DONE

- [x] M2.0 `src/syzygy/astrology/base.py` (`AstrologyEngine` protocol)
- [x] M2.0b `src/syzygy/astrology/policy.py` (`TransitAspectPolicy`, orb
      table, 11 tests in `tests/astrology/test_policy.py`)
- [x] M2.1 Interactively inspect `AstrologicalSubjectFactory.from_birth_data(...)
      .model_dump()` output to confirm exact per-point field names
      (see IMPLEMENTATION_PLAN.md §2.2)
- [x] M2.2 `src/syzygy/astrology/kerykeion_backend.py`: `calculate_natal`
      (IMPLEMENTATION_PLAN.md §2.3)
- [x] M2.3 `kerykeion_backend.py`: `calculate_transits`
      (IMPLEMENTATION_PLAN.md §2.4). **Deviation from the plan's literal
      description**: Kerykeion 5.12.9's `AspectsFactory.dual_chart_aspects`
      resolves `active_points` as the intersection with *both* subjects'
      own `active_points`, so the transiting subject must itself request
      `Ascendant`/`Medium_Coeli` (at the placeholder location) for natal
      axis targets to survive at all - confirmed interactively, not
      inferred. Any aspect where the *transiting* side is an axis is
      discarded before conversion, so no location-dependent value ever
      reaches a domain object; see the "Deviation" comment in
      `kerykeion_backend.calculate_transits` and
      `test_current_location_invariance` /
      `test_raw_aspects_never_use_an_axis_as_the_transiting_source`.
      Also: Kerykeion's `Medium_Coeli` is renamed to `Midheaven` on
      conversion, to match `syzygy.astrology.policy.NATAL_ANGLE_TARGETS`.
- [x] M2.4 `src/syzygy/astrology/ranking.py`: `TransitRanker`
      (IMPLEMENTATION_PLAN.md §2.5). Uses
      `TransitAspectPolicy.max_orb_degrees` (not a flat per-aspect-type
      table) as `orb_closeness`'s denominator, so the Moon's tighter
      policy cap makes its ratio harsher at a given absolute orb - this
      is what actually produces the "slow planet outranks same-orb Moon
      aspect" behavior the plan's own acceptance criteria call for; a
      flat table with the plan's suggested weights (Moon body weight tied
      with Sun at 1.0) cannot produce that ordering on its own.
- [x] M2.5 `tests/astrology/test_kerykeion_backend.py` — fixed birth-data
      fixtures, DST boundary (cross-checked against Python's own
      `zoneinfo`, not just Kerykeion's own output), non-US birthplace,
      current-location invariance test (DESIGN.md §25.2) via monkeypatching
      the module's placeholder-location constants
- [x] M2.6 `tests/astrology/test_ranking.py`
- [x] M2.7 `syzygy dev astrology` CLI command for manual inspection —
      takes birth data via flags (no saved-profile lookup yet - that's
      M4.5/M4.9)

## M3 — Sortes — DONE

- [x] M3.1 `src/syzygy/sortes/entropy.py` (`EntropyCollector`)
- [x] M3.2 `src/syzygy/sortes/draw.py` (`unbiased_index`, `draw_card`)
- [x] M3.3 `tests/sortes/test_entropy.py`, `tests/sortes/test_draw.py`
      (determinism, all-78-reachable, uniformity smoke test)

## M4 — Daily reading state machine and storage — DONE

- [x] M4.1 `src/syzygy/domain/reading.py` (`ReadingStatus`,
      `ALLOWED_TRANSITIONS`, `Reading`)
- [x] M4.2 `tests/domain/test_reading_state_machine.py`
- [x] M4.3 `src/syzygy/storage/database.py`, `migrations.py` (schema +
      append-only migration framework)
- [x] M4.4 `tests/storage/test_migrations.py` (incl. `UNIQUE` constraint proof)
- [x] M4.5 `src/syzygy/storage/profiles.py` (CRUD) (IMPLEMENTATION_PLAN.md §4.2).
      Added `tests/storage/test_profiles.py` (not separately itemized in the
      plan, but profiles.py is deterministic CRUD - covered per the
      workflow's "add tests for any deterministic behavior" rule).
- [x] M4.6 `src/syzygy/storage/readings.py` (state-machine-respecting
      writes; `create_prepared` handles the `IntegrityError` race).
      **Deviations from the plan's literal signatures**: (1) migration 1's
      `readings` table had no column for `TarotDraw.drawn_at_utc` - added
      migration 2 (`card_drawn_at_utc`), append-only per the migrations
      policy, rather than editing migration 1. (2) every write function
      past `create_prepared` takes an explicit `now: datetime` keyword arg
      (not in the plan's sketch) so `updated_at` never calls
      `datetime.now()` internally - callers pass `clock.now_utc()`,
      consistent with AGENTS.md's single-clock-source rule.
- [x] M4.7 `src/syzygy/storage/reading_service.py`:
      `get_or_create_todays_reading` orchestration — depends on M4.6,
      M2.3 (needs a real or fixture `AstrologyEngine`), and M3 (done).
      Builds a minimal `InterpretationContext` inline (card, ranked
      transits, Sun/Moon placements, ascendant sign, empty
      `knowledge_chunks`) rather than depending on M7.5's
      `context_builder.py` or M6's knowledge retrieval, neither of which
      exist yet - `_build_context` is explicitly commented as a
      placeholder to be replaced once M7.5 lands. Added
      `syzygy.domain.astrology.sign_for_longitude` (pure degree math, no
      engine dependency) since `NatalChart` only stores
      `ascendant_longitude`, not a sign string. On provider failure, marks
      `INTERPRETATION_FAILED` and returns (no in-process auto-retry) -
      resolving an internal-doc tension where `interpretation/base.py`
      says the retry-once policy "lives in the caller" while
      IMPLEMENTATION_PLAN.md §7.3 describes it as provider-internal
      (repair-instruction retries against the model, which only a real
      provider can do, are left to M7.7-7.9).
- [x] M4.8 `tests/storage/test_readings.py` — same-day idempotency,
      retry-without-redraw, crash-recovery-after-DRAWN — depends on M4.7.
- [x] M4.9 `syzygy profile create` / `syzygy profile list` / `syzygy chart`
      CLI commands — depends on M4.5. `chart` takes an optional
      `--profile-id`, required only when more than one profile is saved.

## M5 — TUI ritual — DONE

- [x] M5.1 `src/syzygy/tui/app.py` — app shell, `SCREENS`, and
      `SyzygyServices` (connection/clock/astrology/provider injected, so
      tests substitute a fixture engine + `FixtureProvider` wholesale).
      **Additions to the plan**: `syzygy tui` (and bare `syzygy`, per
      DESIGN.md §20) launch it — `tests/test_cli.py`'s no-arguments test
      became a `--help` test accordingly; `storage.database.connect` grew
      a `check_same_thread` flag because Textual thread workers touch the
      connection off the main thread.
- [x] M5.2 `screens/welcome.py`, `profile_create.py`, `profile_select.py`.
      Profile creation is two-phase (form → resolved-values confirmation)
      per DESIGN.md §6.1, with manual coordinate/timezone entry only —
      geocoding stays an optional extra.
- [x] M5.3 `screens/home.py`. Its sky preview calls a new
      `reading_service.rank_current_transits` rather than composing
      engine + policy + ranker in the TUI; the snapshot *stored* on a
      reading is still the one calculated at draw time.
- [x] M5.4 `widgets/wheel.py` (`WheelWidget`, Line API + `set_interval`,
      posts `WheelImpulse`/`WheelDisturbance`/`WheelRelease` plus a
      `WheelNotReady` for a too-early `ENTER`; records into an injected
      `EntropyCollector` and nothing else). A test parses the module's
      imports to prove it can never reach `sortes.draw`/`sortes.deck`.
- [x] M5.5 `screens/wheel.py`, `screens/reveal.py`. **Deviation**:
      `reading_service.get_or_create_todays_reading` was split into
      `draw_todays_reading` (synchronous, provider-free) and
      `interpret_reading` (async), with the old function now composing
      the two — the reveal must show a committed card before any model
      call, and retry-after-failure needs an interpretation-only entry
      point. Behaviour and ordering are unchanged for existing callers.
- [x] M5.6 `widgets/tarot_card.py`, `widgets/alignment.py`,
      `widgets/transit_badge.py`, `widgets/glyph.py` (glyph set +
      ASCII fallbacks behind `SYZYGY_ASCII=1`; real terminal capability
      detection is still M9.2).
- [x] M5.7 `screens/reading.py` + `widgets/reading_panel.py` — esoteric,
      conventional, and INPUTS views over stored data; interpretation runs
      in an exclusive worker; failure shows DESIGN.md §23's copy with `[R]`
      retry against the same context.
- [x] M5.8 `screens/chart.py`, `screens/archive.py` (list-only until M8).
      Added `storage.readings.list_readings` + `get_by_id` — the list part
      of M8.1; `card_frequency`/`suit_frequency` remain M8.1's.
- [x] M5.9 `syzygy.tcss`
- [x] M5.10 Textual `Pilot` tests (`tests/tui/`): full ritual to a
      `COMPLETE` reading, reopening without redrawing, failure-then-retry
      keeping the same card, archive reopening without re-interpreting,
      wheel event/entropy contract, navigation, widget formatting, and
      100×32/80×24/60×18 plus mid-flow resize.

Left for later milestones on purpose: a dedicated "terminal too small"
state and compact mode (M9.3), knowledge chunks in the interpretation
context (the INPUTS view says plainly when none were supplied), and
archive statistics (M8).

## M6 — Book of Thoth ingestion (+ optional companion sources) — DONE

Full spec: `docs/THOTH_INGESTION_MAP.md` (Tier 0 / Book of Thoth) and
`docs/KNOWLEDGE_SOURCES.md` (multi-source tier policy + Tier 1 companion
source structure — DuQuette, Ziegler). Tier 1 ingestion was implemented in
the same pass as Tier 0 (by explicit request), rather than as an optional
fast-follow.

- [x] M6.1 `src/syzygy/knowledge/normalize.py` (Tier 0: header/footer
      stripping, page-marker extraction — ingestion map §4, §5)
- [x] M6.2 `src/syzygy/knowledge/segment.py` (Tier 0: heading detection —
      ingestion map §8)
- [x] M6.3 `src/syzygy/knowledge/store.py` (writes to `knowledge_sources`/
      `knowledge_chunks`, source-agnostic; `replace_source` deletes and
      re-inserts a whole source atomically via explicit `BEGIN`/`COMMIT`,
      matching `migrations.apply_all`'s pattern under this project's
      `isolation_level=None` connections — a bare `with conn:` does not
      provide atomicity there)
- [x] M6.4 New migration (version 3): `knowledge_chunks_fts` (SQLite FTS5
      external-content virtual table + sync triggers) — appended to
      `_MIGRATIONS`, migrations 1-2 untouched
- [x] M6.5 `src/syzygy/knowledge/ingest.py` (pipeline orchestration for
      all three sources; per-`source_type` `INGESTION_VERSIONS` constant
      for idempotent re-ingest detection; chunking approximates the
      600-1200 token target as a 900-word paragraph-boundary budget, no
      tokenizer dependency)
- [x] M6.6 `src/syzygy/knowledge/retrieve.py` (exact card lookup,
      Tier-0-before-Tier-1 ordering via SQL `CASE`; FTS5 `bm25()` search)
- [x] M6.7 `syzygy knowledge ingest <pdf>` / `syzygy knowledge status` CLI
- [x] M6.8 Golden tests against the real PDFs (skipped if absent locally -
      they are gitignored `docs/*.pdf`): Major/Minor/Court retrieval,
      `book_of_thoth_aliases` resolution (`the_magus` only resolves via
      its "The Juggler" alias, not its display name), no cross-section
      bleed, Tier 0-ahead-of-Tier-1 ordering, Tier-0-only unaffected by
      absent companions
- [x] M6.9 `tests/fixtures/thoth_pdf_pages/*.txt` (Major/Minor/Court/
      image-gallery excerpts) + a lightweight always-run sanity test
- [x] M6.10 DuQuette strategy (`normalize.extract_duquette_blocks` +
      `segment.segment_duquette`): position-based header stripping;
      per-line (not whole-block) heading matching, since DuQuette's
      headings share a text block with an adjacent subtitle line (e.g.
      `"ATUO\nTHE FOOL"`, `"TWO OF WANDS\nDOMINION"`) rather than
      standing alone; **the quick-reference appendix's exact boundary was
      verified as PDF pages 275-290** (via its own running header, not
      the doc's ~280+ estimate) and is **excluded from ingestion
      entirely**, not per-card-tagged - KNOWLEDGE_SOURCES.md explicitly
      allows this if it "adds more noise than value," and its
      card-name-shaped lines are too compressed/inconsistent to map
      reliably per card
- [x] M6.11 Ziegler strategy (`segment.segment_ziegler`): confirmed no
      embedded page markers and derived the PDF-page-to-printed-page
      offset (7) *dynamically* by cross-checking the TOC against real
      in-body Major Arcana headings, rather than trusting §4.4's
      single-data-point estimate. **Deviation**: that offset formula only
      holds for the Major Arcana - Court/Minor sections are not evenly
      offset from their TOC page number, and most numbered-Minor cards
      have no extractable heading text at all (the title is embedded in a
      full-page illustration, confirmed e.g. for Three of Cups). Court and
      Minor sections are instead located via one real anchor heading each
      (`KNIGHT OF WANDS`, `ACE OF WANDS`) plus a verified fixed 2-PDF-page
      step per card within each group.
- [x] M6.12 `ingest.py`: filename-based `source_type` auto-detection
      (`detect_source_type`) + `--source-type` CLI override, dispatching
      to the matching segmenter
- [x] M6.13 `retrieve.py`: tier-aware ordering (Tier 0 before Tier 1 for
      the same `card_id`)
- [x] M6.14 Tests: Tier 0-only retrieval unaffected by uningested
      companions; Tier 0 ranks ahead of Tier 1 when both are ingested for
      the same card

Not carried over from the plan's original sketch: the six-trump appendix
(Book of Thoth PDF pages 112-137) does not, in the actual file, carry six
separate per-card headings - it reads as one continuous essay with only
one heading-shaped marker (`"The Fool---i. Silence; ..."`). It is captured
as a single `card_appendix` section anchored to `the_fool` rather than
force-split six ways; see the comment above
`segment._BOT_APPENDIX_CARDS` in `src/syzygy/knowledge/segment.py`.

## M7 — Interpretation

- [x] M7.1 `src/syzygy/domain/interpretation.py` (context + result schemas)
- [x] M7.2 `src/syzygy/interpretation/base.py` (`InterpretationProvider` protocol)
- [x] M7.3 `src/syzygy/interpretation/providers/fixture.py` (`FixtureProvider`)
- [x] M7.4 `tests/interpretation/test_fixture_provider.py`
- [x] M7.5 `src/syzygy/interpretation/context_builder.py`
      (IMPLEMENTATION_PLAN.md §7.2) — depends on M2 (natal/transit data)
      and M6 (knowledge chunks); can be stubbed/tested against
      hand-built fixtures before either is finished. Decan cards also
      include the natal placement of their ruling planet.
- [x] M7.6 `src/syzygy/interpretation/prompts.py` (`PROMPT_VERSION = "daily-v1"`).
      Holds the whole prompt contract, not just the system prompt:
      `SYSTEM_PROMPT` (DESIGN.md §13.5), `build_user_prompt` (deterministic
      rendering of an `InterpretationContext`), `RESPONSE_JSON_SCHEMA`
      (derived from `InterpretationResult` minus the provenance fields, so
      the constraint a provider applies cannot drift from the schema that
      validates the reply), and `build_repair_prompt` for §13.4's single
      retry — providers stay transport-only per AGENTS.md.
      **Also wired M7.5 in** (the note the previous session left here):
      `reading_service` now calls `interpretation.context_builder` with
      `PROMPT_VERSION` and the drawn card's `knowledge.retrieve_for_card`
      chunks, capped at `MAX_KNOWLEDGE_CHUNKS_PER_SOURCE = 3` per source
      (DESIGN.md §12.2 "only the top few"; per-source rather than overall so
      Tier 0's length cannot crowd out the Tier 1 companions). Its interim
      `_build_context`/`_INTERIM_PROMPT_VERSION` are gone.
      **Bug found by that wiring**: `context_builder` unconditionally looked
      up a natal `Ascendant` *placement*, but `KerykeionAstrologyEngine`
      returns only the ten transit bodies as placements and carries the
      angles as `ascendant_longitude`/`midheaven_longitude` — so every real
      reading would have raised, and a ranked transit onto an angle would
      have raised too. Angles are now excluded from the placement lookup
      (the Ascendant already reaches the model as `ascendant_sign`), and
      `tests/interpretation/test_context_builder.py`'s fixture chart no
      longer invents angle placements the real engine never produces.
- [x] M7.7 `src/syzygy/interpretation/providers/llama_cpp.py` — depends on M7.5, M7.6.
      Talks to `llama-server`'s OpenAI-compatible `/v1/chat/completions` over
      plain `httpx` (no SDK), constrained with `response_format:
      json_schema` built from `prompts.RESPONSE_JSON_SCHEMA`, and defaults to
      `http://127.0.0.1:8080/v1` (localhost-only, DESIGN.md §28). Response
      parsing/validation (markdown-fence tolerance, provenance stamping, the
      single repair-turn retry of DESIGN.md §13.4) now lives in a new shared
      `syzygy.interpretation.providers.structured_output` module, written so
      `openai.py`/`anthropic.py` (M7.8/M7.9) reuse it rather than
      reimplementing the same validate-then-repair logic per provider.
      Tests use `httpx.MockTransport` via a test-only `transport=` argument
      on the provider — no real server, no new test dependency. Also added
      `tests/interpretation/conftest.py` (`sample_context`/`build_sample_context`)
      so provider tests share one fixture context instead of each
      reimplementing `FixtureProvider`'s test helper.
- [x] M7.8 `src/syzygy/interpretation/providers/openai.py` — depends on M7.5, M7.6.
      Plain `httpx` against `api.openai.com`'s Chat Completions endpoint
      (same shape `llama_cpp.py` talks to), reusing `structured_output.py`
      for parse/validate/repair. API key resolved via the new
      `syzygy.interpretation.providers.api_keys` module (keyring first,
      `OPENAI_API_KEY` env var fallback, DESIGN.md §13.3) unless passed
      explicitly.
- [x] M7.9 `src/syzygy/interpretation/providers/anthropic.py` — depends on M7.5, M7.6.
      Plain `httpx` against `api.anthropic.com`'s Messages API. Differs from
      the other two providers in wire shape: system prompt is a top-level
      field, not a `messages` role, and a reply's text lives in a list of
      content blocks that this provider concatenates. Key resolution via
      `api_keys` with `ANTHROPIC_API_KEY` fallback, same as M7.8.
      **Also added**: `src/syzygy/interpretation/providers/api_keys.py`
      (`resolve_api_key`/`store_api_key`/`delete_api_key`/
      `has_stored_api_key`), namespaced per provider in the OS keyring so
      M7.10's `model configure`/`model status` CLI has something to call.
- [ ] M7.10 `syzygy model status` / `syzygy model configure` CLI
- [x] M7.11 Context-builder tests (inclusion/exclusion rules per card
      astrology type) — depends on M7.5

## M8 — Archive

- [ ] M8.1 `src/syzygy/storage/readings.py`: `list_readings`,
      `card_frequency`, `suit_frequency` — depends on M4.6
- [ ] M8.2 `screens/archive.py` (full: list, detail, reopen, frequency view)
      — depends on M8.1, M5.8
- [ ] M8.3 Tests: reopening a past reading renders stored data verbatim
      (no recalculation)

## M9 — Polish and release

- [ ] M9.1 Original visual theme (`syzygy.tcss`)
- [ ] M9.2 Glyph capability/fallback layer (DESIGN.md §18.5)
- [ ] M9.3 Compact terminal mode + "too small" state
- [ ] M9.4 `syzygy doctor` grown to check knowledge base + provider config
- [ ] M9.5 Install/packaging documentation
- [ ] M9.6 License review of any dependency added since M0
- [ ] M9.7 `docs/adr/` review for staleness
