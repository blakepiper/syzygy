# Syzygy — Task Checklist

Ordered, ID'd checklist derived from `IMPLEMENTATION_PLAN.md`. Check off
(`- [ ]` → `- [x]`) as you complete each task, and add a one-line note if
you deviated from the plan. Dependencies are noted inline; unless stated
otherwise, tasks within a milestone are sequential.

**Next recommended task: M4.5.**

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

## M4 — Daily reading state machine and storage

- [x] M4.1 `src/syzygy/domain/reading.py` (`ReadingStatus`,
      `ALLOWED_TRANSITIONS`, `Reading`)
- [x] M4.2 `tests/domain/test_reading_state_machine.py`
- [x] M4.3 `src/syzygy/storage/database.py`, `migrations.py` (schema +
      append-only migration framework)
- [x] M4.4 `tests/storage/test_migrations.py` (incl. `UNIQUE` constraint proof)
- [ ] M4.5 `src/syzygy/storage/profiles.py` (CRUD) (IMPLEMENTATION_PLAN.md §4.2)
- [ ] M4.6 `src/syzygy/storage/readings.py` (state-machine-respecting
      writes; `create_prepared` handles the `IntegrityError` race) —
      depends on M4.5 for `Profile` round-tripping to be testable end-to-end,
      but can be implemented against a raw profile_id string first
- [ ] M4.7 `src/syzygy/storage/reading_service.py`:
      `get_or_create_todays_reading` orchestration — depends on M4.6,
      M2.3 (needs a real or fixture `AstrologyEngine`), and M3 (done)
- [ ] M4.8 `tests/storage/test_readings.py` — same-day idempotency,
      retry-without-redraw, crash-recovery-after-DRAWN — depends on M4.7
- [ ] M4.9 `syzygy profile create` / `syzygy profile list` / `syzygy chart`
      CLI commands — depends on M4.5

## M5 — TUI ritual

- [ ] M5.1 `src/syzygy/tui/app.py` — app shell, `SCREENS`
- [ ] M5.2 `screens/welcome.py`, `profile_create.py`, `profile_select.py` —
      depends on M4.5/M4.9
- [ ] M5.3 `screens/home.py` — depends on M4.7 (or a fixture
      `AstrologyEngine` if M2/M4 aren't finished yet — do not block TUI
      work on real astrology, per DESIGN.md Milestone 5 guidance)
- [ ] M5.4 `widgets/wheel.py` (`WheelWidget`, Line API + `set_interval`,
      emits impulse/disturbance/release, calls `syzygy.sortes` only) —
      depends on M3 (done)
- [ ] M5.5 `screens/wheel.py`, `screens/reveal.py` — depends on M5.4
- [ ] M5.6 `widgets/tarot_card.py`, `widgets/alignment.py`,
      `widgets/transit_badge.py`, `widgets/glyph.py`
- [ ] M5.7 `screens/reading.py` + `widgets/reading_panel.py` — uses
      `FixtureProvider` (done, no dependency on M2/M6/M7.2+)
- [ ] M5.8 `screens/chart.py`, `screens/archive.py` (basic, list-only until M8)
- [ ] M5.9 `syzygy.tcss`
- [ ] M5.10 Textual `Pilot`-based tests for key flows, wheel events, resize

## M6 — Book of Thoth ingestion (+ optional companion sources)

Full spec: `docs/THOTH_INGESTION_MAP.md` (Tier 0 / Book of Thoth) and
`docs/KNOWLEDGE_SOURCES.md` (multi-source tier policy + Tier 1 companion
source structure — DuQuette, Ziegler). Read both before starting M6.1.
**Ship Tier 0 (M6.1-M6.9) completely before starting Tier 1 (M6.10+)** —
Tier 1 is optional/additive per `DESIGN.md` §30's acceptance criteria.

- [ ] M6.1 `src/syzygy/knowledge/normalize.py` (Tier 0: header/footer
      stripping, page-marker extraction — ingestion map §4, §5)
- [ ] M6.2 `src/syzygy/knowledge/segment.py` (Tier 0: heading detection —
      ingestion map §8) — depends on M6.1
- [ ] M6.3 `src/syzygy/knowledge/store.py` (writes to `knowledge_sources`/
      `knowledge_chunks`, source-agnostic) — depends on M4.3 (done)
- [ ] M6.4 New migration: `knowledge_chunks_fts` (SQLite FTS5 virtual
      table) — append to `_MIGRATIONS`, do not edit migration 1
- [ ] M6.5 `src/syzygy/knowledge/ingest.py` (Tier 0 pipeline orchestration,
      ingestion map §12; `source_type="book_of_thoth"`) — depends on M6.1-M6.4
- [ ] M6.6 `src/syzygy/knowledge/retrieve.py` (exact card lookup + FTS5,
      source-agnostic query shape) — depends on M6.4, M6.5
- [ ] M6.7 `syzygy knowledge ingest <pdf>` / `syzygy knowledge status` CLI —
      depends on M6.5
- [ ] M6.8 Golden tests: correct retrieval for one Major, one numbered
      Minor, one Court card; alias resolution; no cross-section chunks —
      depends on M6.6
- [ ] M6.9 `tests/fixtures/thoth_pdf_pages/*.txt` small fixtures (ingestion
      map §13)
- [ ] M6.10 Extend `normalize.py`/`segment.py` with a DuQuette strategy:
      position/length-based header stripping (exact-string matching won't
      work — OCR noise, see `docs/KNOWLEDGE_SOURCES.md` §3.1), heading
      detection for `ATU <roman>` / `<RANK> OF <SUIT>` /
      `<COURT> OF <SUIT>`, and exclusion or distinct tagging of the
      ~pages-280+ quick-reference appendix (§3.2) — depends on M6.1-M6.3,
      independent of M6.10 being done before/after M6.11
- [ ] M6.11 Extend `normalize.py`/`segment.py` with a Ziegler strategy:
      first confirm PDF-page-to-printed-page offset and check for embedded
      page markers (§4.4, not yet verified), then heading detection for
      the `<CARD TITLE>` / `Key Words: ...` pattern (§4.3) — depends on
      M6.1-M6.3
- [ ] M6.12 `ingest.py`: source-type auto-detection from filename or
      `--source-type` CLI flag, dispatching to the right normalize/segment
      strategy — depends on M6.10 and/or M6.11
- [ ] M6.13 `retrieve.py`: tier-aware ordering (Tier 0 chunks before Tier 1
      chunks for the same `card_id`) — depends on M6.12
- [ ] M6.14 Tests: Tier 0-only retrieval unaffected by companion sources
      being uningested; Tier 0 ranks ahead of Tier 1 when both are
      ingested for the same card — depends on M6.13

## M7 — Interpretation

- [x] M7.1 `src/syzygy/domain/interpretation.py` (context + result schemas)
- [x] M7.2 `src/syzygy/interpretation/base.py` (`InterpretationProvider` protocol)
- [x] M7.3 `src/syzygy/interpretation/providers/fixture.py` (`FixtureProvider`)
- [x] M7.4 `tests/interpretation/test_fixture_provider.py`
- [ ] M7.5 `src/syzygy/interpretation/context_builder.py`
      (IMPLEMENTATION_PLAN.md §7.2) — depends on M2 (natal/transit data)
      and M6 (knowledge chunks); can be stubbed/tested against
      hand-built fixtures before either is finished
- [ ] M7.6 `src/syzygy/interpretation/prompts.py` (`PROMPT_VERSION = "daily-v1"`)
- [ ] M7.7 `src/syzygy/interpretation/providers/llama_cpp.py` — depends on M7.5, M7.6
- [ ] M7.8 `src/syzygy/interpretation/providers/openai.py` — depends on M7.5, M7.6
- [ ] M7.9 `src/syzygy/interpretation/providers/anthropic.py` — depends on M7.5, M7.6
- [ ] M7.10 `syzygy model status` / `syzygy model configure` CLI
- [ ] M7.11 Context-builder tests (inclusion/exclusion rules per card
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
