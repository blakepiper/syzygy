# SYZYGY - ARCHITECTURE HANDOFF

**Purpose:** Instructions for a frontier reasoning/coding model (for example GPT-5.6 Sol or Claude Opus) to architect the Syzygy repository so that smaller, cheaper models can implement and extend it later without repeatedly re-solving foundational decisions.

**Audience:** A strong model working in the repository for a limited, high-value architecture pass.

**Primary reference:** `DESIGN.md`

**Project state at the time this document was written:** The repository has been initialized and contains `DESIGN.md` and a local copy of Aleister Crowley's *The Book of Thoth* PDF. Little or no implementation should be assumed.

---

# 1. Your Role

You are not being asked to write the entire application.

Your job is to make **high-quality original decisions once**, encode those decisions clearly in the repository, and reduce the amount of architectural reasoning required from future implementation agents.

Think of yourself as the senior architect and lead engineer establishing:

- boundaries;
- domain models;
- data contracts;
- schemas;
- persistence structure;
- dependency policy;
- interfaces;
- implementation order;
- testing strategy;
- source-data structure;
- prompt/context contracts;
- failure semantics;
- conventions for future agents.

A smaller implementation model should be able to enter the repository later, read a small number of files, pick up one bounded task, and implement it correctly without needing to rediscover the philosophy of the application.

The highest-value output of this session is therefore not raw code volume.

It is **good irreversible decisions, explicit contracts, clear task decomposition, and repository-local context**.

---

# 2. Read Before Acting

Before changing the repository:

1. Read `DESIGN.md` in full.
2. Inspect the repository tree.
3. Inspect the actual *Book of Thoth* PDF enough to understand its structure and extraction characteristics.
4. Identify which decisions in `DESIGN.md` are:
   - fixed product decisions;
   - provisional technical recommendations;
   - unresolved implementation choices.
5. Preserve fixed product decisions unless there is a serious technical contradiction.
6. If you change a provisional technical recommendation, record the reason explicitly.

Do not treat this as a greenfield brainstorming task.

The product concept has already been worked through.

Your task is to **stabilize and operationalize it**.

---

# 3. Architectural Goal

The architecture should allow a future smaller model to work from explicit contracts rather than broad intent.

A good small-model task should look like:

> Implement `TransitRanker` according to `IMPLEMENTATION_PLAN.md`, section M2.5. Do not change public schemas. Run the named tests and update `TASKS.md`.

A bad small-model task looks like:

> Figure out how astrology should work and integrate it into the app.

Your architecture pass should transform as many future tasks as possible from the second form into the first.

---

# 4. Core Product Invariants

These decisions are foundational and should be treated as architectural invariants.

## 4.1 Self, Cosmos, Chance

Syzygy combines:

```text
SELF
saved natal chart

COSMOS
current deterministic astrological transits

CHANCE
one truly random Thoth Tarot card

        ↓

SYZYGY
LLM synthesis of the three
```

The LLM is an interpreter.

It is not allowed to calculate the astrology or select the card.

---

## 4.2 Astrology is deterministic application data

The application should use a dedicated astrology library rather than implementing astronomical calculations itself.

The current preferred implementation is Kerykeion.

Do not build an independent ephemeris engine.

Do not spend substantial effort testing whether Kerykeion knows astronomy.

Tests should verify:

- our adapter calls it correctly;
- our data normalization is correct;
- our transit-selection policy is correct;
- our persistence is correct;
- our prompts receive the intended facts.

Keep Kerykeion behind an internal interface so it can be replaced later if needed.

---

## 4.3 Tarot is random

The tarot portion is chance.

v0.1 decisions:

- Crowley-Harris Thoth Tarot;
- all 78 cards;
- upright only;
- no reversals;
- one card;
- equal probability;
- one canonical daily reading per profile per local calendar day;
- no rerolling of the canonical daily card.

The chance subsystem is called **Sortes** internally.

---

## 4.4 The Wheel contributes entropy

The interactive wheel is not just decoration.

Production draws should combine:

- operating-system cryptographic randomness;
- high-resolution user interaction timing;
- session-specific entropy.

The resulting draw must be unbiased across 78 cards.

The application should not pretend that user timing alone is cryptographically secure.

---

## 4.5 Book of Thoth grounding is source-first

The LLM should not rely on its general training knowledge for Thoth meanings when local source material is available.

Primary retrieval strategy:

1. deterministic retrieval of the drawn card's relevant section;
2. deterministic retrieval of structurally relevant general material;
3. optional lexical or semantic retrieval for additional context.

Do not begin by blindly embedding the entire PDF into generic chunks.

---

## 4.6 Two registers of interpretation

Every generated daily reading should provide two views of the same alignment:

### Esoteric

Thelemic / Hermetic / astrological / alchemical / Qabalistic where grounded.

### Conventional

Plain-language practical meaning for the day:

- what may be salient;
- what tensions to notice;
- what to reflect on;
- what to watch for.

The distinction is conceptually inspired by Buddhism's two-truths framing, but the application should not make inflated claims that its generated prose constitutes Buddhist "ultimate truth."

---

## 4.7 TUI first

The primary application is a terminal user interface.

The TUI should be visually distinctive and interaction-heavy.

The project should not silently drift into:

- a React web dashboard;
- a SaaS layout;
- a generic chatbot;
- a CRUD application with occult styling.

The core experience is ritualized interaction in the terminal.

---

## 4.8 Local first

Profiles, readings, chart data, source knowledge, and history are local.

A hosted LLM may be optionally configured.

The application should still be able to:

- load profiles;
- calculate astrology;
- turn the wheel;
- draw the card;
- persist the reading state;
- retrieve source material;

without a cloud model.

Interpretation can fail independently without invalidating the oracle result.

---

# 5. What This Architecture Pass Should Produce

At minimum, leave the repository with these artifacts:

```text
AGENTS.md
ARCHITECTURE_HANDOFF.md
IMPLEMENTATION_PLAN.md
TASKS.md

pyproject.toml

src/syzygy/
    ...

tests/
    ...

docs/
    THOTH_INGESTION_MAP.md

src/syzygy/resources/
    thoth_deck.yaml
```

The exact tree can vary if there is a better reasoned structure, but future agents should have obvious places to look for domain logic, integrations, resources, persistence, and UI.

---

# 6. Create `AGENTS.md` as the Repository's Persistent Operating Manual

`AGENTS.md` should be short enough that every implementation agent can read it.

It should contain only durable rules.

Do not turn it into another 10,000-word design document.

It should include instructions such as:

- Read `DESIGN.md` before changing product behavior.
- Read the relevant milestone in `IMPLEMENTATION_PLAN.md`.
- Do not alter fixed product decisions casually.
- Keep domain logic independent of Textual widgets.
- Keep Kerykeion behind the astrology adapter.
- The LLM never calculates astrology.
- The LLM never selects or changes a tarot card.
- Use all 78 Thoth cards.
- Cards are upright only.
- One canonical daily draw per profile/day.
- Failed interpretation never causes redraw.
- Retrieval is structural-first.
- Do not introduce LangChain, LlamaIndex, hosted vector DBs, agent frameworks, or a web frontend without explicit reason.
- Prefer explicit Python over framework-heavy abstraction.
- Add or update tests with each deterministic behavior change.
- Run relevant tests before marking work complete.
- Update `TASKS.md`.
- Do not leave the repository with knowingly broken tests.

Also include the commands future agents should normally run:

```bash
pytest
ruff check .
...
```

Only list commands that actually exist in the configured repository.

---

# 7. Create `IMPLEMENTATION_PLAN.md`

This is the most important artifact for small-model implementation.

`DESIGN.md` explains what the product should be.

`IMPLEMENTATION_PLAN.md` must explain **how this repository will build it**.

It should be implementation-specific.

For every milestone, define:

- files to create or modify;
- classes/functions/interfaces;
- public schemas;
- storage changes;
- dependency use;
- expected inputs/outputs;
- relevant tests;
- acceptance criteria;
- explicitly deferred work.

Example quality level:

```text
M2.4 - Transit policy

Create:
src/syzygy/astrology/policy.py

Define:
TransitAspectPolicy
AspectOrbRule

Responsibilities:
- Hold Syzygy-owned orb limits.
- Filter raw Kerykeion aspects.
- Never rank aspects.

Inputs:
list[RawTransitAspect]

Outputs:
list[TransitAspect]

Tests:
- conjunction at 2.99 passes
- conjunction at 3.01 fails
- Moon aspect at 1.49 passes
- Moon aspect at 1.51 fails
- ASC target applies 2.0 degree cap
```

That is much better than:

> Add transit filtering.

Aim for bounded work units.

---

# 8. Create `TASKS.md`

Translate the implementation plan into a concise execution queue.

Tasks should be:

- checkable;
- ordered;
- small;
- independently testable where practical;
- named consistently with milestones.

Example:

```markdown
## M1 - Tarot domain

- [ ] M1.1 Define tarot enums and schemas
- [ ] M1.2 Create canonical `thoth_deck.yaml`
- [ ] M1.3 Implement deck loader
- [ ] M1.4 Validate exactly 78 unique cards
- [ ] M1.5 Add deck consistency tests
```

Avoid enormous items like:

- [ ] Build astrology
- [ ] Build AI
- [ ] Build TUI

A small model should be able to complete many individual tasks without needing project-wide reasoning.

---

# 9. Freeze Important Schemas Early

One major way expensive architectural reasoning can help later models is by stabilizing the data contracts.

Create the core Pydantic domain schemas before much implementation.

Expected domain objects include:

```text
BirthData
NatalChart
NatalPlacement
NatalHouse
NatalAspect

TransitSnapshot
TransitAspect
RankedTransit

TarotCard
TarotDraw

Profile

KnowledgeSource
KnowledgeChunk
KnowledgeHit

InterpretationContext
InterpretationResult

Reading
ReadingStatus
```

Do not expose raw Kerykeion types beyond the adapter.

Do not expose raw provider API objects beyond LLM adapters.

Do not let Textual screens become de facto domain models.

---

# 10. Separate Domain Models From Infrastructure Models

Use a layered structure.

A reasonable target:

```text
src/syzygy/
├── domain/
├── astrology/
├── sortes/
├── knowledge/
├── interpretation/
├── storage/
├── resources/
└── tui/
```

### `domain/`

Pure application data and invariants.

No Textual imports.

No Kerykeion imports if avoidable.

No OpenAI/Anthropic SDK response objects.

### `astrology/`

Third-party astrology adapter.

Transit policy.

Ranking.

Normalization into domain models.

### `sortes/`

Entropy collection.

Random draw.

Deck loading.

### `knowledge/`

PDF ingestion.

Normalization.

Segmentation.

Retrieval.

### `interpretation/`

Prompt/context construction.

Provider abstraction.

Structured output validation.

### `storage/`

SQLite schema, migrations, repositories.

### `tui/`

Textual application state and presentation.

This separation allows smaller models to work locally without understanding every subsystem.

---

# 11. Do Not Over-Abstract

The project needs boundaries, not enterprise architecture.

Avoid:

- dependency injection containers;
- service locators;
- event buses;
- microservices;
- generic plugin frameworks;
- generic repository patterns everywhere;
- excessive interface layers;
- dynamically registered "engines" for things with only one implementation.

Use protocols/interfaces when there is a concrete boundary that protects the project:

Good examples:

```text
AstrologyEngine
InterpretationProvider
Clock
SemanticIndex
```

Bad examples:

```text
TarotCardFactoryProviderManager
ProfilePersistenceStrategyFactory
ReadingWorkflowEventBus
```

Small models perform better when the architecture is explicit and shallow.

---

# 12. Kerykeion Integration

Treat Kerykeion as a trusted mathematical dependency.

Do not reproduce its calculations.

Create one adapter:

```text
src/syzygy/astrology/kerykeion_backend.py
```

The adapter should:

1. accept Syzygy `BirthData`;
2. call Kerykeion;
3. convert results into Syzygy domain models;
4. calculate current transit data;
5. expose only normalized application data.

Future application code should never need to know:

- Kerykeion class names;
- Kerykeion serialization shapes;
- internal Kerykeion enum names;
- whether a future version changes its object model.

Tests should focus on adapter behavior and application policy.

Do not build a redundant astronomy correctness suite.

---

# 13. Transit Policy Must Belong to Syzygy

The astrology library may expose many aspects.

Syzygy decides which ones matter for a daily interpretation.

Encode the policy in normal Python data/configuration.

v0.1 uses major aspects:

```text
conjunction
opposition
square
trine
sextile
```

The currently intended maximum orbs are:

```text
conjunction   3.0°
opposition    3.0°
square        3.0°
trine         3.0°
sextile       2.0°
```

Additional narrower caps apply to:

- transiting Moon;
- natal angles.

Keep this policy versioned.

The ranking logic should be deterministic.

Do not let the LLM decide which transits "sound important."

---

# 14. Design the Transit Ranking Contract Now

Create an explicit scoring approach.

The goal is not mathematical astrology truth.

The goal is deterministic selection of a small number of salient aspects.

The score may consider:

```text
orb tightness
aspect type
transiting body
natal target
applying/separating
```

Keep weights in one place.

The context builder should consume `RankedTransit` objects, not raw Kerykeion output.

Document:

- why each weight exists;
- expected number of returned aspects;
- tie-breaking;
- what happens if few aspects are in orb.

This prevents future models from improvising different ranking systems.

---

# 15. Canonical Thoth Data Is a High-Value Frontier-Model Task

Create:

```text
src/syzygy/resources/thoth_deck.yaml
```

with all 78 cards.

This is one of the best uses of a strong model because it is:

- finite;
- important;
- reused everywhere;
- symbolically specialized;
- easy for weaker models to corrupt if left unresolved.

Each card should have a stable ID and appropriate metadata.

Possible fields:

```yaml
id:
display_name:
full_name:
arcana:
suit:
rank:
court:
element:
astrology:
  planet:
  sign:
  decan:
qabalah:
  sephira:
aliases:
```

Not every field applies to every card.

Do not fabricate false symmetry merely to fill all fields.

Where authoritative correspondences are uncertain, leave fields null and document the source decision.

Validate the dataset programmatically:

- exactly 78 cards;
- exactly 22 Major;
- exactly 56 Minor;
- correct suit counts;
- correct court counts;
- unique IDs;
- unique canonical identities.

---

# 16. Inspect the Actual `Book of Thoth` PDF

Do not leave PDF structure discovery to later implementation agents.

Create:

```text
docs/THOTH_INGESTION_MAP.md
```

based on the actual file in this repository.

Document:

- filename;
- file hash;
- whether the PDF has a usable text layer;
- approximate page count;
- PDF page number versus printed page number offset;
- table of contents behavior;
- recurring headers/footers;
- chapter heading patterns;
- Major Arcana section structure;
- Minor Arcana section structure;
- court-card section structure;
- tables that may not extract cleanly;
- unusual typography;
- line-break behavior;
- hyphenation behavior;
- any OCR-like artifacts;
- card-title aliases needed to map text to canonical IDs;
- recommended extraction rules.

If feasible, also create a small parser test fixture based on a few representative pages.

Do not prebuild a huge ingestion system merely because the PDF exists.

The architecture pass should remove uncertainty.

---

# 17. Knowledge Retrieval Architecture

Prefer simple, inspectable retrieval.

## Stage 1

Structural lookup.

For a drawn card, retrieve the chunks mapped directly to that card.

## Stage 2

Optional related structural material.

Examples:

- suit introduction;
- court-card doctrine;
- general astrology;
- relevant planetary material.

## Stage 3

Lexical retrieval using SQLite FTS5.

## Stage 4

Optional semantic retrieval if later testing shows it adds value.

Do not make embeddings a v0.1 prerequisite.

The architecture should allow them later without forcing every implementation model to reason about vector infrastructure now.

---

# 18. Preserve Source Provenance

Every knowledge chunk should retain:

```text
source ID
source file hash
section ID
section type
card ID if applicable
page start
page end
chunk index
text hash
```

The interpretation context should retain the IDs of chunks used.

A future archive should be able to answer:

> What source material did this reading use?

This is more important than sophisticated RAG machinery.

---

# 19. Interpretation Context Is a First-Class Artifact

Do not build prompts directly inside provider adapters.

Create:

```text
InterpretationContext
```

and a deterministic context builder.

This is a critical architectural boundary.

The context builder should decide:

- which natal placements matter;
- which transits matter;
- which Thoth material is included;
- which card correspondences matter;
- what metadata is passed to the model.

The provider should only turn that context into a model request.

This allows:

- provider swapping;
- prompt testing;
- local model testing;
- context inspection;
- regression tests.

A future small model should not need to understand the whole astrology system to add an Anthropic provider.

---

# 20. Structured Interpretation Output

Require a Pydantic schema.

A reasonable starting shape:

```text
InterpretationResult
├── alignment_title
├── esoteric
│   ├── summary
│   └── body
├── conventional
│   ├── summary
│   ├── body
│   ├── watch_for[]
│   └── reflection
└── source_chunk_ids[]
```

Do not let the application parse arbitrary generated prose into sections.

Use provider-specific structured-output capabilities where available, but keep the application schema provider-independent.

---

# 21. Provider Strategy

Design for:

```text
FixtureProvider
LocalOpenAICompatibleProvider
OpenAIProvider
AnthropicProvider
```

The first provider to implement should probably be `FixtureProvider`.

Why:

- the entire UI and reading workflow can be built without spending tokens;
- deterministic tests become possible;
- model integration cannot block product development.

The local runtime can later use an OpenAI-compatible `llama.cpp` server.

Do not bundle multi-gigabyte model weights into the Python package.

---

# 22. Do Not Choose a Permanent Local Model Yet

Model recommendations age quickly.

Instead define requirements:

- modern instruct model;
- approximately 4B-8B as a practical local target;
- good structured output adherence;
- sufficient context window;
- GGUF availability;
- acceptable CPU inference.

Let configuration select the model.

If you recommend a current default during this architecture pass, put it in documentation/config examples, not hard-coded application logic.

---

# 23. Daily Reading State Machine

Define the reading lifecycle explicitly.

Recommended states:

```text
PREPARED
DRAWN
CONTEXT_READY
INTERPRETING
COMPLETE
INTERPRETATION_FAILED
```

Important persistence rule:

**Commit the card immediately after the random draw.**

Do not wait for the LLM.

Example:

```text
calculate cosmos
      ↓
create PREPARED reading
      ↓
wheel + draw
      ↓
persist DRAWN + card
      ↓
retrieve knowledge
      ↓
persist CONTEXT_READY
      ↓
call model
      ↓
COMPLETE
```

If the application crashes after `DRAWN`, it must recover the same card.

This is a key invariant and should have explicit tests.

---

# 24. One Reading Per Local Day

The database should enforce:

```text
UNIQUE(profile_id, consultation_local_date)
```

Do not implement this only in UI logic.

The canonical daily reading is a domain/storage invariant.

When the same profile opens Syzygy again that day:

- return the saved reading;
- do not permit a hidden reroll;
- allow regeneration of interpretation only if appropriate, using unchanged oracle inputs.

A future free-consultation mode can use a different domain object or explicit flag.

Do not weaken the daily invariant now for hypothetical later features.

---

# 25. Storage Should Be Boring

Use SQLite.

Prefer explicit SQL and small repository modules.

Avoid an ORM unless there is a concrete benefit.

Use migrations.

Store structured snapshots as JSON where the schema is large and naturally nested.

Good SQLite candidates:

```text
profiles
readings
knowledge_sources
knowledge_chunks
```

Do not prematurely normalize every astrological coordinate into relational tables.

The archive primarily needs:

- exact historical snapshot;
- searchable metadata;
- stable provenance.

---

# 26. Preserve Historical Inputs

A reading should preserve enough data that future versions do not reinterpret the past using new calculations.

Store:

```text
consultation timestamps
card
transit snapshot
selected transits
astrology policy version
Sortes version
context snapshot
source chunk IDs
source hash
provider
model
prompt version
interpretation
```

Old readings should remain old readings.

Do not recalculate historical astrology every time they are opened.

---

# 27. Profile Data

A profile should save both:

- original birth inputs;
- calculated natal chart.

The application should not recalculate the chart every startup.

Reasons:

- performance;
- historical stability;
- provenance;
- future migration control.

The user may eventually choose to discard original birth inputs after chart calculation, but that is not required for v0.1.

---

# 28. Current Location

Do not make current geographic location part of v0.1.

Use:

- exact natal birth location;
- current timestamp;
- geocentric transits;
- transit-to-natal aspects.

Do not calculate current-location Ascendant/houses unless a later feature explicitly requires relocation astrology.

Do not ask for GPS.

Do not introduce current-location permissions.

---

# 29. Time Handling

Create a testable `Clock` abstraction.

Production:

```text
SystemClock
```

Tests:

```text
FixedClock
```

Store UTC timestamps.

Also preserve local timestamp and timezone for daily identity.

Do not scatter calls to `datetime.now()` throughout the codebase.

This is a small architectural decision with large testing benefits.

---

# 30. Sortes Randomness Contract

Separate:

```text
EntropyCollector
DrawGenerator
```

The collector gathers/mixes entropy.

The generator maps random bytes to one unbiased integer in `[0, 77]`.

Use operating-system randomness as part of every production draw.

User interaction augments it.

For deterministic tests, inject a test entropy source.

Ensure there is no accidental path from a development seed into production usage.

Store only an entropy digest/provenance token, not raw user key history.

---

# 31. The Wheel UI Must Not Own Randomness Logic

The Textual wheel widget should emit events such as:

```text
WheelImpulse
WheelDisturbance
WheelRelease
```

or call a narrow entropy collection interface.

The widget should not itself choose a tarot card.

This allows:

- deterministic unit tests;
- alternate future interfaces;
- CLI testing;
- clear separation of presentation from oracle mechanics.

---

# 32. TUI Architecture

Use Textual.

Build custom widgets where the product identity requires them.

High-value custom widgets:

```text
WheelWidget
TarotCardWidget
AlignmentWidget
TransitBadge
Glyph
ReadingPanel
```

Use Textual for:

- layout;
- key binding;
- events;
- worker tasks;
- styles;
- screen lifecycle.

Do not reproduce an entire rendering engine unnecessarily.

---

# 33. Treat Animation as Product Logic

The interaction sequence matters:

```text
SELF resolves
      ↓
COSMOS resolves
      ↓
CHANCE waits
      ↓
wheel motion
      ↓
card draw
      ↓
card reveal
      ↓
transit modifiers attach
      ↓
three points align
      ↓
interpretation appears
```

Document this sequence.

Do not let later models reduce it to:

```text
Button("Get Reading")
```

Use fixture data to prototype the experience before real LLM integration.

---

# 34. Do Not Begin With the LLM

Implementation order should intentionally delay real model integration.

A strong sequence is:

```text
M0 repository
M1 tarot domain/data
M2 astrology
M3 Sortes
M4 persistence/state machine
M5 TUI ritual with fixture interpretation
M6 Book of Thoth ingestion
M7 real interpretation providers
M8 archive
M9 polish
```

This ensures most of the project can be tested without spending model tokens or debugging inference runtimes.

---

# 35. Do Not Begin With Embeddings

Likewise:

```text
structural retrieval
        ↓
FTS5
        ↓
evaluate
        ↓
optional embeddings
```

Do not assume semantic vectors are automatically better.

The source corpus has explicit known card structure.

Use that structure.

---

# 36. Tests Should Protect Our Decisions, Not Re-Prove Dependencies

High-value tests include:

### Deck

- 78 unique cards;
- expected arcana counts;
- expected suit counts;
- no reversed-state field in v0.1 draw logic.

### Astrology adapter

- profile input passes through correctly;
- output normalizes into Syzygy schemas;
- saved natal chart reloads unchanged;
- fixed consultation time produces stable adapter output;
- Syzygy orb policy filters correctly;
- ranking logic is deterministic.

Do not create a large independent suite proving planetary positions against external astronomy unless an actual problem appears.

### Sortes

- all 78 outcomes reachable;
- deterministic injected seed works in tests;
- production source uses OS entropy;
- draw distribution has no obvious bias;
- card locks after draw.

### Reading state

- same profile/date cannot create two canonical readings;
- failure after draw preserves card;
- retry interpretation does not redraw.

### Knowledge

- mapped card returns correct primary chunks;
- page provenance survives;
- unrelated sections do not replace exact card lookup.

### Interpretation

- context contains expected facts;
- previous readings are absent;
- provider receives immutable context;
- output schema validates.

### TUI

- key flows;
- screen state;
- wheel events;
- resize behavior;
- crash recovery flow.

---

# 37. Build `FixtureProvider` Early

A fixture model provider should return realistic structured interpretation data.

Use it for:

- TUI development;
- screenshots;
- tests;
- archive testing;
- reading workflow.

This allows smaller implementation models to complete almost everything before the real local-model setup exists.

The fixture should not be a trivial `"hello world"` result.

Make it look structurally like a real reading.

---

# 38. Documentation Strategy

Keep documentation roles distinct.

## `DESIGN.md`

Product intent.

What Syzygy is.

Why it works this way.

## `ARCHITECTURE_HANDOFF.md`

Instructions to a strong model on how to shape the repository for downstream implementation.

This file.

## `AGENTS.md`

Compact permanent rules for every coding agent.

## `IMPLEMENTATION_PLAN.md`

Concrete technical plan.

## `TASKS.md`

Execution checklist.

## `docs/THOTH_INGESTION_MAP.md`

Facts about the actual PDF and ingestion strategy.

Avoid duplicating the same information in every file.

Cross-reference instead.

---

# 39. Optimize Context for Future Small Models

A future implementation task should not require reading everything.

Design the repository so an agent can often read only:

```text
AGENTS.md
relevant IMPLEMENTATION_PLAN section
relevant source files
relevant tests
```

It should consult `DESIGN.md` when product intent is ambiguous.

This reduces both token usage and architectural drift.

---

# 40. Add Comments Only Where They Preserve Reasoning

Do not fill the codebase with prose.

Use comments for:

- non-obvious domain decisions;
- important invariants;
- reasons behind unusual calculations;
- security/privacy implications;
- intentional limitations.

Example:

```python
# The daily card is committed before LLM generation.
# Interpretation failure must never result in another draw.
```

Useful.

Example:

```python
# Loop over transits.
for transit in transits:
```

Not useful.

---

# 41. Encode Decisions in Types and Constraints

Do not rely only on documentation.

Examples:

Instead of merely saying "one reading per day":

```sql
UNIQUE(profile_id, consultation_local_date)
```

Instead of saying "cards are upright":

Do not include an `orientation` field in v0.1 unless there is a strong future-compatibility reason.

Instead of saying "provider cannot choose card":

Do not pass a randomizer callback to the provider.

Instead of saying "Kerykeion should not leak":

Return Syzygy domain types from the adapter.

Architecture should make the correct path the easiest path.

---

# 42. Avoid Future-Proofing That Weakens the Present Design

Do not build generic abstractions for:

- multiple tarot decks;
- arbitrary divination systems;
- reversed cards;
- web/mobile frontends;
- multiplayer profiles;
- cloud synchronization;
- plugins;
- agent tools;
- multiple astrology traditions.

A future version can add them.

v0.1 should strongly model the actual product:

```text
Thoth
upright
one card
daily
TUI
local-first
```

Paradoxically, clear present-day boundaries make future refactors easier than vague generic abstractions.

---

# 43. When To Use the Strong Model's Judgment

Spend frontier reasoning on choices that are expensive to reverse.

Examples:

- domain schema boundaries;
- reading lifecycle;
- DB schema;
- source-data representation;
- PDF section-mapping strategy;
- prompt/context contract;
- transit ranking policy;
- error semantics;
- provider abstraction;
- canonical Thoth metadata;
- module boundaries.

Do not spend substantial premium time on:

- writing obvious CRUD;
- repetitive tests;
- Textual boilerplate;
- basic CLI plumbing;
- formatting;
- straightforward serialization;
- simple repository methods.

Leave those to downstream models.

---

# 44. Write ADRs for Major Deviations

If you make a major architectural decision not already covered by `DESIGN.md`, create a small architecture decision record.

Suggested:

```text
docs/adr/
    0001-use-kerykeion.md
    0002-reading-commit-before-interpretation.md
```

Use ADRs sparingly.

Create one when:

- the decision is expensive to reverse;
- multiple reasonable alternatives existed;
- a future agent may otherwise undo it.

Do not create ADRs for trivial implementation choices.

---

# 45. Dependency Policy

Prefer few, mature dependencies.

Expected core categories:

```text
Textual
Pydantic
Kerykeion
platformdirs
PyMuPDF
```

Potential supporting packages:

```text
httpx
keyring
geopy
timezonefinder
```

Only add a dependency when it meaningfully reduces risk or complexity.

Avoid:

```text
LangChain
LlamaIndex
general agent frameworks
hosted vector DB clients
web frameworks
large orchestration libraries
```

unless the repository later develops a demonstrated need.

---

# 46. Geocoding

Birthplace resolution is an onboarding convenience.

Keep geocoding separate from astrology.

Input:

```text
"Alexandria, Virginia, USA"
```

Output:

```text
label
latitude
longitude
IANA timezone
```

Save the resolved result.

Do not repeatedly geocode every startup.

Manual entry should remain possible if external geocoding fails.

If the initial geocoder requires network access, document that onboarding is the exception to the otherwise local-first architecture.

---

# 47. Prompt Engineering Should Be Versioned

Create prompt templates in repository files or explicit Python constants with stable versions.

Example:

```text
PROMPT_VERSION = "daily-v1"
```

A reading stores its prompt version.

The prompt should instruct the model:

- use only supplied astrology;
- use supplied source material as Thoth grounding;
- do not invent aspects;
- do not change card meaning to force coherence;
- produce both interpretive registers;
- avoid concrete factual future predictions;
- keep the result concise;
- paraphrase rather than quote excessively.

Future prompt changes should not make old readings ambiguous.

---

# 48. Make Model Inputs Inspectable

The application should support a user/developer view of the interpretation context.

This is valuable for:

- trust;
- debugging;
- prompt improvement;
- evaluating local models;
- understanding why a reading came out a certain way.

Design this now by making `InterpretationContext` serializable.

Do not construct a giant opaque string that is immediately discarded.

---

# 49. History Is Structured Data First

Store:

```text
card
astrology
context
interpretation
provenance
```

Do not store only a formatted reading blob.

This enables future queries such as:

```text
all readings with The Hermit
all readings during Saturn square natal Venus
card counts by suit
major versus minor frequency
readings during specific transit windows
```

History analysis should later be able to operate without reparsing prose.

---

# 50. Do Not Feed History Into Daily Readings

The canonical daily reading is:

```text
SELF + COSMOS + CHANCE
```

not:

```text
SELF + COSMOS + CHANCE + everything the app previously told you
```

Previous readings belong to separate retrospective analysis features.

Encode this separation in the context builder.

---

# 51. Failure Semantics

Architect failure paths explicitly.

## Astrology failure

No draw.

The Self/Cosmos state is incomplete.

## Draw failure

No reading committed.

## Post-draw knowledge failure

Keep card.

Allow reduced or deferred interpretation.

## LLM failure

Keep card.

Keep astrology snapshot.

Mark interpretation failure.

Allow retry.

## Invalid structured output

Repair once.

Then fail interpretation only.

At no point after successful draw should a technical error result in a new card.

---

# 52. Logging and Privacy

No telemetry by default.

Debug logs should not contain:

- API keys;
- raw birth profiles;
- raw PDF text;
- full remote prompts unless an explicit development mode is enabled;
- raw entropy key sequences.

Log identifiers and timings where possible.

Example:

```text
reading_id
provider
model
chunk_ids
latency
error type
```

---

# 53. Make the Repository Easy to Review

At the end of the architecture pass:

1. run tests;
2. run lint/type checks;
3. inspect the tree;
4. remove unused scaffolding;
5. make sure docs agree with code;
6. ensure `TASKS.md` reflects actual status;
7. leave a concise final note in `IMPLEMENTATION_PLAN.md` describing the next task.

The next implementation model should not have to infer where work stopped.

---

# 54. Suggested Initial Repository Shape

A good target is:

```text
.
├── AGENTS.md
├── ARCHITECTURE_HANDOFF.md
├── DESIGN.md
├── IMPLEMENTATION_PLAN.md
├── TASKS.md
├── README.md
├── pyproject.toml
│
├── Book of Thoth.pdf
│
├── docs/
│   ├── THOTH_INGESTION_MAP.md
│   └── adr/
│
├── src/
│   └── syzygy/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── clock.py
│       │
│       ├── domain/
│       │   ├── astrology.py
│       │   ├── knowledge.py
│       │   ├── profile.py
│       │   ├── reading.py
│       │   └── tarot.py
│       │
│       ├── astrology/
│       │   ├── base.py
│       │   ├── kerykeion_backend.py
│       │   ├── policy.py
│       │   └── ranking.py
│       │
│       ├── sortes/
│       │   ├── deck.py
│       │   ├── draw.py
│       │   └── entropy.py
│       │
│       ├── knowledge/
│       │   ├── ingest.py
│       │   ├── normalize.py
│       │   ├── retrieve.py
│       │   ├── segment.py
│       │   └── store.py
│       │
│       ├── interpretation/
│       │   ├── base.py
│       │   ├── context_builder.py
│       │   ├── prompts.py
│       │   ├── schemas.py
│       │   └── providers/
│       │       ├── fixture.py
│       │       ├── llama_cpp.py
│       │       ├── openai.py
│       │       └── anthropic.py
│       │
│       ├── storage/
│       │   ├── database.py
│       │   ├── migrations.py
│       │   ├── profiles.py
│       │   ├── readings.py
│       │   └── knowledge.py
│       │
│       ├── resources/
│       │   └── thoth_deck.yaml
│       │
│       └── tui/
│           ├── app.py
│           ├── screens/
│           ├── widgets/
│           └── syzygy.tcss
│
└── tests/
    ├── astrology/
    ├── sortes/
    ├── knowledge/
    ├── interpretation/
    ├── storage/
    └── tui/
```

This is a target, not a requirement to create every empty file immediately.

Avoid meaningless placeholders.

---

# 55. What the Strong Model Should Actually Implement

The ideal architecture session should probably implement enough skeleton to prove the boundaries.

Reasonable implementation scope:

- package configuration;
- core domain schemas;
- canonical deck schema and data;
- DB initialization/migration framework;
- interface/protocol definitions;
- fixture provider;
- basic CLI boot;
- basic Textual boot;
- tests for core schemas/deck;
- perhaps the first vertical skeleton through profile storage.

Do not consume the entire high-end session writing every milestone.

The objective is to leave the project in a state where a smaller model can continue confidently.

---

# 56. Recommended Division of Labor After This Session

## Frontier model

Use for:

- this architecture/bootstrap pass;
- resolving difficult cross-cutting bugs;
- reviewing large milestone boundaries;
- revisiting architecture when actual evidence contradicts the plan;
- improving prompt/context strategy after reading quality evaluation;
- substantial refactors.

## Smaller model

Use for:

- implementing the task queue;
- CRUD;
- schemas already specified;
- tests;
- Textual screens;
- adapters;
- migrations;
- parsing rules;
- CLI commands;
- fixing ordinary test failures;
- incremental polish.

The architecture should deliberately maximize the second category.

---

# 57. Review Cadence

Do not require a frontier model after every task.

A sensible pattern:

```text
frontier architecture pass

        ↓

smaller model:
M0
M1
M2

        ↓

frontier review if needed

        ↓

smaller model:
M3
M4
M5
M6

        ↓

frontier review of:
context construction
prompt quality
major architecture drift

        ↓

smaller model:
M7+
```

Use expensive review where errors would compound.

Do not use expensive review for routine implementation.

---

# 58. How to Review Smaller-Model Work

When the frontier model returns later, do not rewrite working code for stylistic reasons.

Review for:

- violated invariants;
- data loss;
- architectural boundary leaks;
- untested critical behavior;
- accidental framework creep;
- inconsistent schemas;
- provider-specific coupling;
- current-location creep;
- hidden reroll paths;
- incorrect Thoth metadata;
- brittle PDF assumptions;
- prompt hallucination pathways.

Prefer targeted fixes.

Do not destabilize the repository because a different naming style seems prettier.

---

# 59. Signs the Architecture Has Failed

Stop and correct course if future work starts showing these patterns:

### Model-driven domain logic

Prompts are being used to determine:

- astrology;
- card correspondences;
- transit importance;
- draw outcomes.

### Giant context dumps

The whole natal chart and whole book are passed to the model every day.

### UI owns business rules

Textual screen code decides whether another card can be drawn.

### Provider coupling

OpenAI-specific response fields appear in domain models.

### Randomness tied to animation

Changing wheel animation alters probability or breaks tests.

### Retrieval-by-vibes

Semantic search replaces obvious exact card lookup.

### Premature generalization

The project has abstractions for ten future decks but still cannot produce one good daily reading.

### SaaS drift

The TUI becomes a terminal-shaped settings dashboard.

### Hidden non-determinism

Opening yesterday's reading recalculates inputs and changes what it means.

These are architecture bugs, not merely style issues.

---

# 60. Success Criteria for This Architecture Session

Before declaring the architecture pass complete, verify that a smaller model could answer all of these questions from repository-local documents and types:

### Product

- What exactly is a daily reading?
- Why is there only one card?
- Are reversals allowed?
- Can the card be rerolled?
- What does the LLM actually do?
- Why are there two interpretation modes?

### Astrology

- Which library owns calculations?
- Which aspects matter?
- What are the orb limits?
- How are significant transits selected?
- Is current location required?
- Where are raw third-party types converted?

### Tarot

- Where are all 78 cards defined?
- Which names/correspondences are canonical?
- How is the card selected?
- How is the card persisted?

### Knowledge

- How is the PDF structured?
- How is the drawn card's section retrieved?
- Are embeddings required?
- How is source provenance preserved?

### LLM

- What is the provider interface?
- What context does it receive?
- What output schema must it return?
- What happens if generation fails?

### Storage

- Where are profiles stored?
- Where are readings stored?
- What prevents two daily readings?
- What data is immutable?

### TUI

- What are the main screens?
- Which component owns the Wheel?
- How does the reveal sequence work?
- What happens while the model is generating?

### Implementation

- What is the next task?
- Which files should change?
- Which tests prove completion?

If these answers are clear, the architecture pass has done its job.

---

# 61. Final Instruction to the Frontier Model

Do not try to make Syzygy impressive by adding more systems.

Make it impressive by making the core system unusually coherent.

The project's quality depends on a clean relationship between:

```text
SELF
what is fixed about the person

COSMOS
what is fixed about the sky

CHANCE
what is genuinely unresolved until the draw

KNOWLEDGE
what Crowley's symbolic system actually says

INTERPRETATION
what the model can meaningfully synthesize

RITUAL
how the user experiences the transition from one to the next
```

Your job is to encode that relationship so clearly in the codebase that a less capable model cannot easily destroy it by accident.

Make difficult decisions explicit.

Make invariants executable where possible.

Make interfaces narrow.

Make tasks small.

Make the next model's job obvious.

Then stop architecting and let implementation begin.
