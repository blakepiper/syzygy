# Syzygy — Implementation Plan

This translates `DESIGN.md` into this repository's actual architecture.
Where `DESIGN.md` says *what* and *why*, this document says *where* and
*how*. Read `AGENTS.md` first for the durable rules; read the milestone
section below that covers your task before writing code.

Status legend: **DONE** (implemented + tested this session), **NEXT**
(the recommended next milestone), **PLANNED** (specified here, not yet
started).

---

## Milestone 0 — Repository skeleton — **DONE**

`pyproject.toml`, package layout, `ruff`/`pytest`/`mypy` config, CLI entry
point (`syzygy.cli:main`), `LICENSE` (AGPL-3.0, see
`docs/adr/0001-agpl-license-for-kerykeion.md`), `README.md`.

Acceptance (verified): `pip install -e ".[dev]"`, `pytest`, `ruff check .`,
`mypy src`, `syzygy dev deck`, `syzygy doctor` all succeed against a clean
checkout using Python 3.11–3.13.

---

## Milestone 1 — Domain models and Thoth deck — **DONE**

Deliverables and where they live:

- `src/syzygy/domain/tarot.py` — `Arcana`, `Suit`, `CourtRank`, `Element`,
  `Decan`, `CourtSpan`, `AstrologyCorrespondence`, `Qabalah`, `TarotCard`,
  `TarotDraw`. No `orientation`/`reversed` field — enforced by
  `tests/sortes/test_deck.py::test_no_card_has_an_orientation_field`.
- `src/syzygy/domain/astrology.py`, `profile.py`, `knowledge.py`,
  `interpretation.py`, `reading.py` — the rest of the core domain schemas
  (see Milestone 4 for `reading.py`'s state machine in detail).
- `src/syzygy/resources/thoth_deck.yaml` — all 78 cards. Source-grounded
  against `docs/book_of_thoth.pdf`; see `docs/THOTH_INGESTION_MAP.md`
  section 11 for the specific citations, including two attributions a
  generic reference would get wrong (the Emperor/Star Tzaddi-Heh swap, the
  counter-elemental court-card decan spans).
- `src/syzygy/sortes/deck.py` — `load_deck()` (validates + caches),
  `get_card(card_id)`.

Tests: `tests/sortes/test_deck.py` (78/22/56/court counts, unique ids, no
orientation field, two regression guards for the Thoth-specific
attributions above).

Acceptance (verified): `syzygy dev deck` enumerates all 78 cards.

---

## Milestone 2 — Astrology — **DONE**

### 2.1 Done already

- `src/syzygy/astrology/base.py` — the `AstrologyEngine` protocol
  (`calculate_natal`, `calculate_transits`). This is the boundary; nothing
  outside `syzygy.astrology` may import `kerykeion`.
- `src/syzygy/astrology/policy.py` — `TransitAspectPolicy`, orb table,
  Moon/angle caps, `POLICY_VERSION`. Fully implemented and tested
  (`tests/astrology/test_policy.py`, 11 tests). **Do not re-implement
  this** — it already encodes the exact table from `DESIGN.md` section 9.4.

### 2.2 To build: the Kerykeion adapter

Create `src/syzygy/astrology/kerykeion_backend.py`, implementing
`AstrologyEngine`. Kerykeion is pinned at `>=5.12.0` in `pyproject.toml`.

**Before writing the adapter**, run a short interactive check of
Kerykeion's actual return shapes — this session verified the *factory and
aspect* APIs below against Kerykeion 5.12.9's source, but did not enumerate
every field name on the per-point result objects (`KerykeionPointModel`).
Confirm those with something like:

```python
from kerykeion import AstrologicalSubjectFactory
subject = AstrologicalSubjectFactory.from_birth_data(
    name="test", year=1990, month=8, day=7, hour=14, minute=22,
    lat=38.8048, lng=-77.0469, tz_str="America/New_York", online=False,
    zodiac_type="Tropical", houses_system_identifier="P",
)
print(subject.model_dump())
```

and read off the exact keys before writing `_to_natal_placement` below.

**Verified API surface** (Kerykeion 5.12.9, AGPL-3.0 — see
`docs/adr/0001-agpl-license-for-kerykeion.md`):

- `AstrologicalSubjectFactory.from_birth_data(name, year, month, day, hour,
  minute, seconds=0, city=None, nation=None, lng=..., lat=..., tz_str=...,
  online=False, zodiac_type="Tropical", sidereal_mode=None,
  houses_system_identifier="P", active_points=[...])` → `AstrologicalSubjectModel`.
  Passing `online=False` with explicit `lat`/`lng`/`tz_str` makes this a
  **zero-network** call — required, since Syzygy must work offline
  (`DESIGN.md` section 5.4).
- `active_points` — pass exactly
  `["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus",
  "Neptune","Pluto","Ascendant","Medium_Coeli"]` for the **natal** chart
  (matches `syzygy.domain.astrology.TRANSIT_BODIES` plus the two angles).
  Do not pass the library's default point set — it includes lunar nodes,
  Chiron, and Mean Lilith, which `DESIGN.md` section 9.3 explicitly
  excludes from v0.1.
- `AspectsFactory.dual_chart_aspects(first_subject, second_subject,
  active_points=None, active_aspects=None, axis_orb_limit=None)` →
  `DualChartAspectsModel.aspects: list[AspectModel]`. Each `AspectModel`
  has `p1_name`, `p1_owner`, `p2_name`, `p2_owner`, `aspect`, `orbit`
  (the actual orb in degrees), `aspect_degrees`, `aspect_movement:
  Literal["Applying","Separating","Static"]`.
- House system identifier for Placidus is `"P"` (single-char code).
  `DESIGN.md` section 9.2 specifies Placidus as the v0.1 default; store
  `birth.house_system` on `BirthData` and map it to Kerykeion's identifier
  in the adapter (a small dict is enough — do not build a generic
  house-system abstraction for a v0.1 that only ever uses one).

### 2.3 `calculate_natal`

```
def calculate_natal(self, birth: BirthData) -> NatalChart
```

1. Parse `birth.local_date`/`birth.local_time` into year/month/day/hour/minute.
2. Call `AstrologicalSubjectFactory.from_birth_data(...)` with
   `online=False`, the explicit lat/lng/tz_str from `birth`, and the
   `active_points` list above.
3. Convert each requested point into a `NatalPlacement` (body, sign,
   longitude, house, retrograde) — field names confirmed per section 2.2.
4. Call `AspectsFactory.single_chart_aspects(subject)` to get natal-to-natal
   aspects; convert into `NatalAspect` (only `body_a`, `body_b`, `aspect`,
   `orb_degrees` — no ranking or filtering here, this is Self, not Cosmos).
5. Return a `NatalChart` with `astrology_engine="kerykeion"`,
   `astrology_engine_version` read from `importlib.metadata.version("kerykeion")`
   (do not hardcode it), and `chart_schema_version="chart-v1"`.

**Invariant**: pure function of `birth` (plus the pinned Kerykeion
version) — the same `BirthData` must always produce the same `NatalChart`.
Do not let this method read a clock or any mutable state.

### 2.4 `calculate_transits`

```
def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot
```

1. Build a **transiting subject** for `instant` using
   `AstrologicalSubjectFactory.from_iso_utc_time(...)` (or `from_birth_data`
   with `instant`'s UTC fields) — **do not include `Ascendant` or
   `Medium_Coeli` in this subject's `active_points`**. This is how the
   "no current-location astrology" invariant (`DESIGN.md` section 3.2) gets
   enforced in code, not just by convention: the transiting subject simply
   never has location-dependent points to leak. Use a fixed placeholder
   location (e.g. `lat=0, lng=0, tz_str="UTC"`) — geocentric planetary
   longitudes for the 10 transit bodies do not depend on observer location,
   only house/angle placements do, and this subject requests no houses/angles.
2. Call `AspectsFactory.dual_chart_aspects(transiting_subject, natal_subject,
   active_points=[...10 transit bodies for the transiting side, all natal
   points including Ascendant/MC for the natal side...], active_aspects=
   MAJOR_ASPECTS)`. You will need the original natal `AstrologicalSubjectModel`
   (or enough of it) to pass as `second_subject` — consider whether
   `NatalChart` needs an internal (non-domain, adapter-only) cache of the
   raw Kerykeion subject, or whether recomputing it from `natal.birth_data`
   via `calculate_natal` internals is cheap enough to just do again. Prefer
   recomputing — it keeps `NatalChart` free of any Kerykeion-shaped field
   and this calculation is not performance-sensitive.
3. Convert each `AspectModel` into a `syzygy.domain.astrology.TransitAspect`
   (`transiting_body=p1_name`, `natal_target=p2_name`, `aspect=aspect`,
   `orb_degrees=orbit`, `movement=aspect_movement.lower()`). Do **not**
   filter by `syzygy.astrology.policy` here — return the raw aspect list;
   filtering is the caller's job (or `TransitSnapshot`'s consumer's job),
   so `TransitSnapshot.raw_aspects` genuinely holds everything, per
   `DESIGN.md` section 9.5 ("always retain the complete transit snapshot").
4. Also capture `transiting_positions: list[NatalPlacement]` for the 10
   bodies (no house, since none were requested).
5. Return `TransitSnapshot(instant_utc=instant, transiting_positions=...,
   raw_aspects=..., astrology_policy_version=POLICY_VERSION)` — note this
   snapshot references the *policy version in effect*, not a filtered
   result; `syzygy.astrology.policy.TransitAspectPolicy` is applied by the
   reading service (Milestone 4), not inside the engine.

### 2.5 `syzygy.astrology.ranking` (not yet created)

Create `TransitRanker` per `DESIGN.md` section 9.5:

```python
class TransitRanker:
    def rank(self, aspects: list[TransitAspect]) -> list[RankedTransit]: ...
```

- Input: aspects that have **already passed** `TransitAspectPolicy.filter`.
- Score formula (make every weight a named module-level constant, not a
  magic number inline):
  `score = aspect_weight[aspect.aspect] * orb_closeness * transiting_body_weight[...] * natal_target_weight[...] * applying_modifier`
  where `orb_closeness = 1 - (orb_degrees / max_orb_for_this_aspect)`
  (tighter orb → closer to 1).
- Suggested starting weights (adjust only with a documented reason —
  update this section if you do): aspect_weight — conjunction/opposition/
  square = 1.0, trine = 0.85, sextile = 0.7. transiting_body_weight —
  Sun/Moon = 1.0, personal planets (Mercury/Venus/Mars) = 0.9, social
  (Jupiter/Saturn) = 0.85, outer (Uranus/Neptune/Pluto) = 0.8.
  natal_target_weight — Sun/Moon/Ascendant = 1.0, personal planets = 0.9,
  other natal points = 0.8. applying_modifier — 1.1 if applying, 1.0 if
  separating/static.
- Sort descending by score; assign `rank` 1..N; return the **top 6** (if
  fewer than 6 aspects passed the policy filter, return all of them — do
  not pad or fabricate).
- Tie-breaking: tighter orb wins; if still tied, stable-sort order (input
  order) — document this rather than leaving it to dict/set iteration order.

Tests (`tests/astrology/test_ranking.py`, not yet created): deterministic
ordering given a fixed input list; top-6 truncation; fewer-than-6 passthrough;
tie-break behavior; a slow-planet-to-personal-point aspect outranks a
same-orb Moon aspect (per `DESIGN.md` section 9.5's guidance that Moon
contacts "should not crowd out every slower transit").

### 2.6 Tests to add

`tests/astrology/test_kerykeion_backend.py` — use 2-3 fixed birth-data
fixtures (a documented public figure's birth data, or synthetic data with
independently-checked planetary longitudes; `DESIGN.md` section 25.1
suggests comparing against an independent ephemeris rather than only
snapshotting Kerykeion's own output). Cover: natal calculation stability
(same input twice → same output), at least one DST-boundary birth
instant, at least one non-US birthplace, and the **current-location
invariance test** from `DESIGN.md` section 25.2 — call
`calculate_transits` for the same UTC instant against subjects built with
different (arbitrary, nonsensical) placeholder locations and assert the
10 transiting body longitudes are identical within tolerance, and that no
house/angle data appears on the transiting side at all.

### Acceptance

```bash
syzygy profile create   # not yet a CLI command - add a minimal one here if needed for manual testing
syzygy dev astrology
```

produce stable structured `NatalChart`/`TransitSnapshot` output. Do not
start Milestone 5 (TUI) work that depends on real astrology until this
milestone's tests pass — fixture-driven TUI work can and should proceed in
parallel using `FixtureProvider`, per Milestone 5 below. (Both are now
done; this ordering note is kept as the rationale for how they were
built.)

---

## Milestone 3 — Sortes — **DONE**

- `src/syzygy/sortes/entropy.py` — `EntropyCollector`, `EntropyEvent`,
  `ENTROPY_ALGORITHM_VERSION`. OS randomness is drawn fresh at `digest()`
  time and mixed via BLAKE2b with a session nonce and recorded events.
- `src/syzygy/sortes/draw.py` — `unbiased_index` (rejection sampling, no
  modulo bias), `draw_card` (digest → index → `TarotDraw`),
  `SORTES_ALGORITHM_VERSION`.

Tests: `tests/sortes/test_entropy.py`, `tests/sortes/test_draw.py` (17
tests total) — determinism given fixed inputs, all-reachable-indices proof,
approximate uniformity smoke test, production default uses `os.urandom`.

**Wired up in Milestone 5**: `syzygy.tui.widgets.wheel.WheelWidget` calls
`.record("impulse"/"disturbance"/"release")` on real key events, and
`syzygy.tui.screens.wheel.WheelScreen` hands the collector to
`reading_service.draw_todays_reading` (which calls
`syzygy.sortes.draw.draw_card`) on release. The widget contains no
randomness or selection logic of its own (`DESIGN.md` section 7.1,
`ARCHITECTURE_HANDOFF.md` section 31) — `tests/tui/test_wheel_widget.py`
asserts it cannot even import the deck or the draw.

---

## Milestone 4 — Daily reading state machine and storage — **DONE**

### 4.1 Done already

- `src/syzygy/domain/reading.py` — `ReadingStatus`, `ALLOWED_TRANSITIONS`,
  `Reading`. Tested in `tests/domain/test_reading_state_machine.py`
  (transition-graph invariants, e.g. `COMPLETE` is terminal, nothing can
  reach `PREPARED`/`DRAWN` except the one legitimate initial edge).
- `src/syzygy/storage/database.py` — `connect`, `open_database`.
- `src/syzygy/storage/migrations.py` — append-only migration list,
  `apply_all`, `current_version`. Migration 1 creates `profiles`,
  `readings` (with the `UNIQUE(profile_id, consultation_local_date)`
  constraint), `knowledge_sources`, `knowledge_chunks`.
  Tested in `tests/storage/test_migrations.py`, including a direct
  `sqlite3.IntegrityError` proof of the daily-uniqueness constraint.

**Migrations are append-only**: to change the schema, add a new
`(version, description, sql)` tuple to `_MIGRATIONS` in
`src/syzygy/storage/migrations.py` — never edit migration 1's SQL text
after it has shipped, even to fix a typo, since a fresh database and an
upgraded database must run through the exact same recorded history.

### 4.2 To build: repositories and the reading service

Not yet created. This is the next piece after Milestone 2 (or can proceed
in parallel — it has no Kerykeion dependency of its own, only a
`AstrologyEngine`-shaped dependency it can receive via injection).

Create `src/syzygy/storage/profiles.py`:

```python
def insert_profile(conn: sqlite3.Connection, profile: Profile) -> None: ...
def get_profile(conn: sqlite3.Connection, profile_id: str) -> Profile | None: ...
def list_profiles(conn: sqlite3.Connection) -> list[Profile]: ...
```

Serialize `NatalChart` to `natal_chart_json` via
`profile.natal_chart.model_dump_json()`; deserialize via
`NatalChart.model_validate_json(...)`. Straightforward CRUD — no ORM.

Create `src/syzygy/storage/readings.py`:

```python
def get_today(conn: sqlite3.Connection, profile_id: str, local_date: str) -> Reading | None: ...
def create_prepared(conn: sqlite3.Connection, ...) -> Reading: ...
def commit_draw(conn: sqlite3.Connection, reading_id: str, draw: TarotDraw) -> Reading: ...
def commit_context(conn: sqlite3.Connection, reading_id: str, snapshot: TransitSnapshot,
                    selected: list[RankedTransit], context: InterpretationContext) -> Reading: ...
def begin_interpreting(conn: sqlite3.Connection, reading_id: str) -> Reading: ...
def complete_interpretation(conn: sqlite3.Connection, reading_id: str,
                             result: InterpretationResult) -> Reading: ...
def fail_interpretation(conn: sqlite3.Connection, reading_id: str) -> Reading: ...
```

Every one of these functions must:
1. Read the current row's `status`.
2. Check the requested transition against
   `syzygy.domain.reading.ALLOWED_TRANSITIONS` **in application code**,
   raising a dedicated `IllegalReadingTransition` exception if not allowed
   — this is a second, defense-in-depth check; the primary enforcement of
   "no reroll" is that there is simply no function here that goes back to
   `PREPARED`/`DRAWN`.
3. Update `status` and only the columns relevant to that transition.
4. Let `INSERT`'s `UNIQUE` constraint be the actual source of truth for
   "one reading per profile per day" — `create_prepared` should catch
   `sqlite3.IntegrityError` on that constraint and re-raise as (or return)
   the existing reading, so callers get "open today's reading" behavior
   for free rather than needing a separate check-then-insert (which would
   race).

Create `src/syzygy/storage/reading_service.py` (or fold into `readings.py`
if it stays small — use judgement) with the actual orchestration function
described in `DESIGN.md` section 5.1's pipeline:

```python
async def get_or_create_todays_reading(
    conn, profile: Profile, clock: Clock, astrology: AstrologyEngine,
    entropy: EntropyCollector, provider: InterpretationProvider,
) -> Reading: ...
```

This function is where the ordering invariant from `DESIGN.md` section
5.1 actually lives in code:
`profile → astrology → entropy ritual → card draw → lock reading inputs →
retrieve knowledge → LLM interpretation → save interpretation`.
If a reading already exists for today, return it immediately without
touching astrology, entropy, or the provider at all — reopening is a pure
read.

### 4.3 Tests to add

`tests/storage/test_readings.py`: first draw creates a reading; a second
call the same day returns the same reading unchanged; an
`INTERPRETATION_FAILED` reading can be retried without a new `card_id`;
simulate a crash by calling `commit_draw` and then constructing a fresh
service call for the same day — it must recover the same card rather than
drawing again (this is the literal test `ARCHITECTURE_HANDOFF.md` section
23 asks for: "kill the flow after DRAWN, restart, prove the same card
survives").

### Acceptance

A test can call `commit_draw`, simulate a restart (new `AstrologyEngine`/
`EntropyCollector`/provider instances, same `conn`), and prove the
recovered `Reading.card_draw.card_id` is unchanged.

---

## Milestone 5 — TUI ritual — **DONE**

Built as sketched below, against a fixture `AstrologyEngine` (in
`tests/tui/conftest.py`, deliberately not in `src/`) and `FixtureProvider`.
See `TASKS.md`'s M5 section for the deviations — chiefly that
`reading_service.get_or_create_todays_reading` was split into
`draw_todays_reading` + `interpret_reading` so the reveal can show a
committed card while interpretation is still running, and that
`syzygy`/`syzygy tui` now launch the app. Per `ARCHITECTURE_HANDOFF.md` section 34 and `DESIGN.md`
Milestone 5: **do not integrate a real LLM provider for this milestone —
use `FixtureProvider` (already implemented,
`syzygy.interpretation.providers.fixture.FixtureProvider`).** This
milestone can start as soon as Milestone 4's reading service exists,
independent of Milestone 2's real astrology adapter if needed — a second
`AstrologyEngine` fixture implementation returning canned `NatalChart`/
`TransitSnapshot` data would unblock TUI work even earlier, if desired.

Suggested structure (`DESIGN.md` section 19):

```
src/syzygy/tui/
├── app.py
├── screens/
│   ├── welcome.py, profile_create.py, profile_select.py, home.py,
│   │   wheel.py, reveal.py, reading.py, chart.py, archive.py,
│   │   knowledge.py, settings.py
├── widgets/
│   ├── wheel.py, tarot_card.py, alignment.py, transit_badge.py,
│   │   glyph.py, reading_panel.py
└── syzygy.tcss
```

Verified this session (see the Textual research summary folded into this
plan): current stable is Textual 8.2.8, `requires-python>=3.9,<4.0`, but a
known asyncio-event-loop regression on Python 3.14 (hence this project's
own `<3.14` pin — see `AGENTS.md`). Key APIs to use:

- **`WheelWidget`**: subclass `Widget`, implement `render_line(y: int) ->
  Strip` (the Line API) for per-row `Segment`-level control of the
  rotating glyph art, driven by a `reactive` angle/frame value updated via
  `set_interval`. `Widget.styles.animate(...)` is for tweening CSS-style
  properties (opacity, offset) — good for the card reveal fade/slide, not
  for the Wheel's frame-by-frame glyph animation.
- The widget must only ever call into `syzygy.sortes.entropy.EntropyCollector`
  (`.record(kind, monotonic_ns)`) and, on release, hand off to
  `syzygy.sortes.draw.draw_card` — it must contain no card-selection logic
  of its own (`DESIGN.md` section 7.1). Emit widget-level messages
  (`WheelImpulse`, `WheelDisturbance`, `WheelRelease`, per
  `ARCHITECTURE_HANDOFF.md` section 31) rather than reaching into
  application state directly from event handlers.
- **LLM calls / long-running work**: use the `@work` decorator
  (`thread=True` for a synchronous provider SDK call, plain `async` `@work`
  for an `httpx`-based async call), with `exclusive=True` on the
  interpretation worker so a stale in-flight call is auto-cancelled if the
  user somehow re-triggers it. Marshal any UI update from a thread worker
  back via `call_from_thread`.
- **Testing**: `async with app.run_test() as pilot:` + `await
  pilot.press(...)`. Add `pytest-textual-snapshot` as a dev dependency
  only once there are screens worth snapshotting — don't add it in this
  milestone's first commit.

### Acceptance

The full ritual (profile → home → wheel → reveal → reading, with fixture
interpretation text) is navigable and coherent using only `FixtureProvider`
— no API key, no local model, no network, ever required to develop or
demo this milestone.

---

## Milestone 6 — Book of Thoth ingestion — **DONE**

Implemented out of order (ahead of Milestones 5 and 7, by explicit
request), with Tier 1 (DuQuette, Ziegler) shipped in the same pass as
Tier 0 rather than as an optional fast-follow. See `TASKS.md`'s M6
section for the specific deviations from this plan's sketch (chunking
uses an approximate word-count budget rather than a real tokenizer; the
six-trump Book of Thoth appendix is one `card_appendix` section rather
than six; DuQuette's quick-reference appendix is excluded from ingestion
rather than per-card-tagged; Ziegler's Court/Minor sections are located
via anchor-plus-fixed-step rather than the Major Arcana's TOC-offset
formula).

Full spec for the canonical (Tier 0) source: `docs/THOTH_INGESTION_MAP.md`
(file hash, page structure, heading-detection rules, header/footer
stripping rules, a concrete 9-step pipeline in that document's section
12). Two supplementary (Tier 1) companion sources were added to `docs/`
after that document was written — DuQuette's *Understanding Aleister
Crowley's Thoth Tarot* and Ziegler's *Tarot: Mirror of the Soul*. Their
structure, text quality, and how they fit into retrieval are documented
in `docs/KNOWLEDGE_SOURCES.md`, which also defines the source-tier policy
this milestone implements. **Read both documents before starting** — do
not re-derive PDF structure from scratch, and do not skip
`KNOWLEDGE_SOURCES.md` section 1 (the tier policy) even if you only plan
to implement Tier 0 ingestion first.

None of the three source PDFs are committed (`.gitignore`: `docs/*.pdf`)
— they're local reference copies. Ingestion reads them directly from
`docs/` on disk regardless of git tracking status; what ingestion
*produces* (chunks, the FTS index) is fine to commit.

Suggested structure (`DESIGN.md` section 21):

```
src/syzygy/knowledge/
├── ingest.py      # orchestrates the pipeline, per source
├── normalize.py   # header/footer stripping, page-marker extraction
├── segment.py     # heading detection → card-scoped sections
├── store.py       # writes knowledge_sources / knowledge_chunks rows
└── retrieve.py    # exact card-id lookup + SQLite FTS5
```

- **Build and ship Tier 0 (Book of Thoth) ingestion first**, completely,
  before touching either companion source — it's the only source that
  gates the "Definition of Done" acceptance criteria in `DESIGN.md`
  section 30. Tier 1 ingestion is additive and optional; the app must
  work correctly with zero companion sources ingested.
- `normalize.py` and `segment.py` need **per-source strategies**, not one
  universal parser — the three sources use three different heading
  conventions and header/footer patterns (`docs/KNOWLEDGE_SOURCES.md`
  sections 3–4). A reasonable shape: one small strategy object/function
  pair per `source_type` (`"book_of_thoth"`, `"duquette_companion"`,
  `"ziegler_mirror_of_soul"`), selected by `ingest.py` based on which file
  is being processed — not a single regex trying to cover all three.
  DuQuette specifically needs position/length-based header stripping
  instead of exact-string matching, because its OCR noise means the same
  running header extracts as a different string on different pages
  (`docs/KNOWLEDGE_SOURCES.md` section 3.1).
- `syzygy knowledge ingest <pdf>` CLI command (add to `syzygy.cli`) drives
  `ingest.py`, auto-detecting `source_type` from the filename or accepting
  an explicit `--source-type` flag. Must be idempotent: hash the file,
  skip if already ingested at the same `ingestion_version` (bump the
  version constant if you change segmentation/chunking logic for that
  source, so a re-ingest is triggered).
- FTS5: add a `knowledge_chunks_fts` virtual table via a **new** migration
  (append to `_MIGRATIONS` in `syzygy.storage.migrations` — do not edit
  migration 1). One shared FTS table across all sources is fine — filter
  by joining back to `knowledge_chunks.source_id` /
  `knowledge_sources.source_type` when a caller needs tier-aware results.
- `retrieve.py` implements exactly the two tiers `DESIGN.md` section 11.2
  specifies, now tier-aware across sources: (1) exact `card_id` match
  against `knowledge_chunks`, returning Tier 0 (`book_of_thoth`) chunks
  first, then any ingested Tier 1 chunks for the same `card_id`; (2) FTS5
  lexical search across whatever has been ingested. No embeddings in this
  milestone (`DESIGN.md` section 11.4 — optional, added later only if
  evaluation shows they help).
- DuQuette's "quick reference" appendix section (`docs/KNOWLEDGE_SOURCES.md`
  section 3.2, approx. PDF pages 280+) duplicates card names in a
  different, noisier format from its main per-card essays. Tag it with a
  distinct `section_type` (e.g. `"quick_reference"`) if ingested at all,
  so `retrieve.py` can deprioritize or exclude it rather than returning
  redundant/conflicting chunks for the same card.

Tests: for at least one Major, one numbered Minor, and one Court card,
exact retrieval against the **Tier 0** source returns the correct chunk(s)
with correct `page_start`/`page_end`; no chunk crosses a card-section
boundary; aliases from `thoth_deck.yaml`'s `book_of_thoth_aliases` resolve
correctly (these were transcribed verbatim from the book's own contents
listing — see `docs/THOTH_INGESTION_MAP.md` section 7). Once Tier 1
ingestion exists: a query against a card with both tiers ingested returns
Tier 0 chunks ranked ahead of Tier 1 chunks; a query against a card with
only Tier 0 ingested is unaffected by the companion sources' absence.

### Acceptance

For representative cards from Major, Minor, and Court categories, the
application retrieves correct primary source material without embeddings,
using only the Tier 0 source. Tier 1 companion-source ingestion for
DuQuette and/or Ziegler may ship in the same milestone or a fast-follow —
it must not block or complicate the Tier 0 acceptance criteria above.

---

## Milestone 7 — Interpretation — **PARTIALLY DONE**

### 7.1 Done already

- `src/syzygy/domain/interpretation.py` — `InterpretationContext`,
  `InterpretationResult`, `EsotericReading`, `ConventionalReading`,
  `CONTEXT_SCHEMA_VERSION`.
- `src/syzygy/interpretation/base.py` — `InterpretationProvider` protocol.
- `src/syzygy/interpretation/providers/fixture.py` — `FixtureProvider`,
  fully implemented, deterministic, no dependencies. Tested in
  `tests/interpretation/test_fixture_provider.py` (4 tests, including the
  Princess-of-Disks no-astrology edge case).

Note: this session deliberately did **not** create a separate
`interpretation/schemas.py` distinct from `domain/interpretation.py` — the
`DESIGN.md` §13.1 file tree suggests one, but `InterpretationResult` *is*
the structured-output schema (validated directly against provider output).
A second parallel schema would be a duplicated source of truth. If a
provider's structured-output feature needs a slightly different wire shape
before conversion, keep that conversion local to that provider module —
don't promote it to a shared `schemas.py` unless two+ providers need to
share it.

### 7.2 To build: context builder

Create `src/syzygy/interpretation/context_builder.py`:

```python
def build_context(
    profile: Profile, card: TarotCard, ranked_transits: list[RankedTransit],
    knowledge_chunks: list[KnowledgeChunk], consultation_local_timestamp: str,
    consultation_local_date: str, prompt_version: str,
) -> InterpretationContext: ...
```

Implements `DESIGN.md` section 12.1/12.2/12.3 precisely:
- Always include: card, canonical correspondences (already on `TarotCard`),
  direct Book of Thoth chunks for the card, the ranked transits as given
  (already limited to ~6 by `TransitRanker`), Sun/Moon/Ascendant natal
  placements, profile display name, consultation timestamp, prompt version.
- Conditionally include (per card's `astrology.type`): if `"planet"`,
  include that planet's natal placement and any ranked transit involving
  it; if `"sign"`, include natal planets in that sign; if `"decan"`,
  include the specific planet/sign pairing (already on the card).
- Never include: the full `NatalChart`, the full `TransitSnapshot`, any
  previous `Reading`, current location. This function's signature
  physically cannot access those (it doesn't take a `TransitSnapshot` or
  a list of past readings as a parameter) — keep it that way rather than
  trusting callers not to pass more than needed.

Tests: assert the built context contains exactly the expected fields for
a sign-attributed card vs. a planet-attributed card vs. a decan card vs. a
Princess (no astrology at all); assert previous-reading data cannot appear
(there's no parameter for it, but add a test asserting the function's
signature doesn't grow one without a corresponding design update — a
simple `inspect.signature` assertion is enough).

### 7.3 To build: prompts + real providers

`src/syzygy/interpretation/prompts.py` — the system prompt encoding the
rules in `DESIGN.md` section 13.5, as a versioned constant (`PROMPT_VERSION
= "daily-v1"`). Keep the prompt itself in this file, not inline in a
provider.

`src/syzygy/interpretation/providers/llama_cpp.py` — talks to a local
OpenAI-compatible `llama-server` endpoint via `httpx`. Binds to
localhost by default (`DESIGN.md` section 28).

`src/syzygy/interpretation/providers/openai.py`,
`src/syzygy/interpretation/providers/anthropic.py` — real hosted
providers. API keys via `keyring` with an environment-variable fallback
(`DESIGN.md` section 13.3) — never read from or written to the SQLite
database. Each provider must validate its raw response into
`InterpretationResult` and retry once with a repair instruction on
validation failure (`DESIGN.md` section 13.4), then raise (letting the
reading service mark `INTERPRETATION_FAILED`) — never return a
partially-valid result.

**Adding a new provider later**: implement `InterpretationProvider`,
convert your SDK's response into `InterpretationResult`, done. No changes
needed to the context builder, the reading state machine, or the TUI.

### Acceptance

The same immutable `Reading` (same `card_draw`, same `transit_snapshot`)
can be interpreted by two different providers without either provider
touching the oracle state.

---

## Milestone 8 — Archive — **PLANNED**

`src/syzygy/storage/readings.py` (extend): `list_readings(conn, profile_id,
limit, offset)`, `card_frequency(conn, profile_id)`,
`suit_frequency(conn, profile_id)`. Pure SQL aggregation over the
`readings` table — no LLM-generated trend analysis in v0.1 (`DESIGN.md`
section 15). Present counts as descriptive only; do not imply statistical
significance in any UI copy (`DESIGN.md` section 15).

TUI: `src/syzygy/tui/screens/archive.py` — list + reopen. Reopening a past
`Reading` must render it exactly as stored (no recalculation) —
`DESIGN.md` section 15.1: "today's oracle must never be conditioned on
previous readings," and symmetrically, past readings must never be
silently updated by today's code.

---

## Milestone 9 — Polish and release — **PLANNED**

Original visual theme, compact terminal mode + glyph fallback layer
(`DESIGN.md` section 18.5 — a capability-detection module, not scattered
Unicode assumptions through view code), `syzygy doctor` grown to check
knowledge-base presence and provider configuration, packaging/install
docs, `docs/adr/` review, license review of anything added since Milestone 0.

---

## Open questions intentionally left for later milestones

- Exact `KerykeionPointModel` field names (Milestone 2.2 — quick,
  bounded, do first).
- Exact local-model recommendation for `llama_cpp.py` — `DESIGN.md`
  section 5.5 deliberately avoids pinning one; put any current
  recommendation in documentation/config examples, not application logic.
- Whether `interpretation/context_builder.py`'s conditional-inclusion
  rules need a "strong current transit involving the card's planet/sign"
  threshold — start with "include if present in the already-ranked top 6",
  revisit only if evaluation shows the context is too sparse or too noisy.
