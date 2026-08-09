# SYZYGY - Design and Architecture

**Status:** v0.1 architecture baseline  
**Date:** 2026-08-07  
**Primary interface:** Terminal user interface (TUI)  
**Working name:** `syzygy`  
**Project type:** Local-first personal divination / reflective practice application

---

## 1. Purpose

Syzygy is a daily divination system that combines three independent sources of meaning:

1. **Self** - the user's saved natal astrological chart.
2. **Cosmos** - the actual astrological relationship between the current sky and that natal chart at the moment of consultation.
3. **Chance** - one genuinely random draw from the full 78-card Crowley-Harris Thoth Tarot, produced through an interactive entropy-gathering ritual.

These three elements are brought into alignment by an LLM-backed interpretation layer.

The name **Syzygy** refers to an astronomical alignment of bodies. Within the application, it becomes the central metaphor:

```text
                    SELF
                     ●
                    / \
                   /   \
                  /     \
                 /       \
                ●─────────●
             COSMOS     CHANCE

                   SYZYGY
```

The application should feel like a small occult machine rather than a horoscope website, chatbot, productivity dashboard, or videogame.

It borrows the tactile interaction philosophy and visual energy of *Balatro* without copying its assets, exact layouts, typography, or game mechanics. It borrows the participatory entropy concept of the TempleOS “God” random-number/oracle functions without copying Terry Davis's code or reproducing TempleOS. Its symbolic vocabulary intentionally blends Western esotericism and Thelema with a restrained Buddhist influence, especially the metaphor of **turning the wheel** and the conceptual distinction between esoteric and conventional readings.

The application is game-like in presentation while remaining an oracle. There are no points, winning states, streak penalties, monetized draws, rarity systems, or mechanics that encourage compulsive rerolling.

---

# 2. Product Thesis

A conventional daily horoscope is mostly deterministic but impersonal.

A conventional tarot draw is personal and evocative but disconnected from any external celestial state.

Syzygy combines:

```text
saved natal chart
        +
current transits
        +
one random Thoth card
        +
curated source knowledge
        ↓
contextual interpretation
```

The LLM is **not the oracle**.

The LLM does not decide the card. It does not calculate the horoscope. It does not invent planetary placements. It receives already-resolved facts and interprets their conjunction.

This separation is one of the most important architectural rules in the project.

---

# 3. Core Concepts

## 3.1 Self

“Self” is represented by a user profile containing the birth information necessary to calculate an accurate natal chart and a saved, versioned result of that calculation.

A profile contains:

- display name;
- exact local birth date;
- exact local birth time;
- birthplace label;
- birthplace latitude;
- birthplace longitude;
- IANA timezone for the birthplace;
- selected house system;
- calculated natal chart;
- astrology engine and version used to calculate it;
- chart schema version;
- creation/update timestamps.

Birth data is entered once during profile creation and saved locally.

The natal chart is also saved. The app must not silently recalculate an existing profile every time it starts. If the astrology engine or calculation policy changes in a future release, recalculation should be an explicit migration so old readings retain their historical inputs.

Multiple profiles are supported.

---

## 3.2 Cosmos

“Cosmos” is the current geocentric planetary state evaluated against the profile's natal chart.

For v0.1, **the user's current geographic location is not required**.

The program uses:

- the exact instant of the first consultation;
- the machine's current timezone to determine the user's local calendar date;
- geocentric current planetary positions;
- transit-to-natal aspects.

The v0.1 reading deliberately does **not** use:

- relocated natal charts;
- current-location houses;
- a current Ascendant;
- a current Midheaven;
- topocentric transit positions;
- astrocartography.

This avoids unnecessary collection of current location data and keeps the astrology model conceptually clean.

The natal chart still requires birth location and birth time because natal houses and angles depend on them.

A daily reading is tied to the exact instant at which it was first created, not an arbitrary noon or midnight chart. That instant is saved with the reading.

---

## 3.3 Chance

“Chance” is one card drawn from the complete 78-card Crowley-Harris Thoth Tarot.

Project decisions for v0.1:

- all 78 cards are used;
- the deck uses Thoth names and structure;
- all cards are upright;
- there are no reversals;
- one card is drawn;
- every card has equal probability;
- the LLM cannot influence the draw;
- a day's card cannot be rerolled.

The chance engine is internally called **Sortes**.

“Sortes” may eventually become the name of a broader pure-chance oracle subsystem, including future TempleOS-inspired word or text divination modes, but those modes are not part of v0.1.

---

## 3.4 Syzygy

A Syzygy is the completed alignment of:

```text
SELF + COSMOS + CHANCE
```

Only after all three components are fixed does interpretation begin.

The interpretation layer receives immutable structured data.

If generation fails, the card and astrology snapshot remain valid and saved. The user can retry interpretation without redrawing or recalculating the underlying oracle state.

---

# 4. Philosophical and Aesthetic Direction

## 4.1 Thelema and Western esotericism

The Thoth Tarot is not being used as interchangeable “tarot imagery.” Its internal symbolic system should matter.

The application should be able to reason from:

- Crowley's analysis in *The Book of Thoth*;
- the astrological correspondences of the cards;
- elements;
- zodiacal and planetary attributions;
- decans;
- Qabalistic structure where relevant;
- alchemical symbolism where relevant;
- the specific titles and symbolic character of Thoth cards.

The project should avoid flattening this material into generic internet tarot keywords.

A card such as **Two of Wands - Dominion** should enter the model with its Thoth-specific astrological correspondence and relevant Crowley source material, not merely with a dictionary entry like “leadership, courage, planning.”

Canonical deck metadata must be human-verifiable and source-based. Do not ask an LLM to invent the application's authoritative correspondence table.

---

## 4.2 Buddhist influence

The principal Buddhist influence in v0.1 is conceptual rather than doctrinal.

### Turning the wheel

The entropy interaction is framed as **turning the wheel**. The user gives the wheel motion through keyboard interaction, supplying timing variation that is mixed into the draw.

The UI may visually evoke a wheel, mandala, or rotating symbolic mechanism, but it should not pretend to reproduce a Buddhist liturgical object or claim doctrinal authenticity.

### Two registers of interpretation

The output is inspired by the Buddhist distinction between levels or registers of truth, but Syzygy should not casually label its own generated prose “ultimate truth.”

Instead, every reading has two views of the same alignment:

1. **Esoteric**
   - symbolic;
   - Thelemic/Hermetic;
   - astrological;
   - alchemical/Qabalistic where justified by the sources;
   - allowed to assume some knowledge of Western esotericism.

2. **Conventional**
   - plain language;
   - practical implications for the day;
   - tensions to notice;
   - themes to reflect on;
   - one useful question to carry through the day.

These are not two independent readings. They are two registers of the same synthesis.

---

# 5. Product Principles

## 5.1 The oracle precedes the interpretation

The order is immutable:

```text
profile
  ↓
astrology
  ↓
entropy ritual
  ↓
card draw
  ↓
lock reading inputs
  ↓
retrieve knowledge
  ↓
LLM interpretation
  ↓
save interpretation
```

Never call an LLM before the random card is fixed.

---

## 5.2 Facts and interpretation are separate

Astrological facts come from the astrology engine.

Randomness comes from the Sortes engine.

Thoth source material comes from the local knowledge store.

The LLM performs synthesis only.

It must not be asked questions like:

> What are today's important transits for this user?

Instead it should receive exact values such as:

```json
{
  "transiting_body": "Saturn",
  "aspect": "square",
  "natal_body": "Venus",
  "orb_degrees": 0.84,
  "movement": "applying"
}
```

---

## 5.3 One canonical daily reading

For v0.1 there is one canonical daily reading per profile per local calendar date.

If a reading already exists:

```text
syzygy today
```

opens the saved reading.

It does not redraw.

This avoids “fishing” for a preferred card and gives the archive a coherent daily structure.

A future version may support a separate free-consultation mode that is explicitly not the canonical daily reading.

---

## 5.4 Local-first

After profile setup and knowledge ingestion, all non-LLM oracle functions should work offline.

The core application must remain useful without an OpenAI, Anthropic, or other hosted account.

A commercial LLM API is an optional interpretation backend, not a dependency of the oracle.

---

## 5.5 No bundled model weights in the base package

The base Python package should not ship multi-gigabyte model files.

Local inference is a first-class path, but model weights are downloaded or configured separately.

Conceptually:

```text
syzygy package
    │
    ├── local model adapter
    │      └── user-selected GGUF model / llama.cpp server
    │
    ├── OpenAI adapter
    │
    └── Anthropic adapter
```

The provider interface must be abstract enough that additional backends can be added later.

A good local target is a modern instruction-tuned model in roughly the 4B-8B range with:

- reliable structured output;
- at least ~16K usable context;
- competent synthesis;
- acceptable CPU inference;
- GGUF availability.

Do not hard-code the product around one model family. Model recommendations will age faster than the application architecture.

---

## 5.6 No generic “AI mystical app” aesthetics

Avoid:

- purple gradient backgrounds;
- generic glowing constellations;
- crystal-ball clip art;
- rounded SaaS cards;
- mobile-dashboard composition;
- excessive emoji;
- “Your magical insight awaits” marketing copy;
- fake scarcity;
- fake mystical authority.

Syzygy should look engineered, strange, dense, intentional, and slightly dangerous.

---

# 6. Primary User Flow

## 6.1 First launch

If there is no profile:

```text
SYZYGY

No self is configured.

[N] Create profile
[Q] Quit
```

Profile creation asks for:

1. display name;
2. birth date;
3. exact local birth time;
4. birthplace.

Birthplace resolution produces:

- human-readable place label;
- latitude;
- longitude;
- IANA timezone.

The user must review these resolved values before chart calculation.

Example:

```text
BIRTHPLACE

Entered:
  Alexandria, Virginia, USA

Resolved:
  38.8048 N
  77.0469 W
  America/New_York

[C] Confirm
[E] Edit
```

Geocoding is an onboarding convenience, not part of astrological calculation itself. Once resolved, coordinates and timezone are saved.

Manual latitude, longitude, and timezone entry must be available as a fallback.

v0.1 assumes the user knows a birth time. “Unknown birth time” mode is deferred.

---

## 6.2 Natal calculation

After confirmation:

```text
CALCULATING SELF
```

The natal chart is calculated once and saved.

The profile summary screen should emphasize useful anchors rather than dumping every field:

```text
BLAKE

☉ Sun        Virgo       14°22'
☽ Moon       Pisces       8°11'
↑ Ascendant  Scorpio     18°43'

Natal chart stored.
```

A detailed chart inspector remains available separately.

---

## 6.3 Daily home screen

Example concept:

```text
┌─────────────────────────────────────────────────────────────┐
│ SYZYGY                                      07 AUG 2026     │
│                                                             │
│ SELF                     COSMOS                    CHANCE    │
│  ●─────────────────────────●─────────────────────────○      │
│                                                             │
│ Blake                                                       │
│ ☉ Virgo     ☽ Pisces     ↑ Scorpio                          │
│                                                             │
│ Current sky resolved.                                       │
│ Chance has not yet entered the alignment.                   │
│                                                             │
│                       [ TURN THE WHEEL ]                     │
│                                                             │
│ C chart     A archive     P profiles     ? help             │
└─────────────────────────────────────────────────────────────┘
```

If today's reading already exists, the primary action becomes:

```text
[ OPEN TODAY'S READING ]
```

---

# 7. The Wheel

The Wheel is the defining interaction.

It is not a decorative loading spinner.

## 7.1 Inputs

At minimum:

- `SPACE`: add impulse;
- `←` / `→`: disturb direction or phase;
- other key presses may contribute entropy;
- `ENTER`: release when the system is ready.

The exact controls can evolve during prototyping.

---

## 7.2 Entropy collection

The draw must never depend solely on user key timing.

Initialize the entropy pool with operating-system cryptographic randomness.

Then mix in high-resolution interaction events such as:

- monotonic timestamp deltas;
- press intervals;
- key-event sequence;
- wheel state at event time.

Do **not** save the literal user key sequence as part of the reading history.

A conceptual construction:

```text
OS_RANDOM
    +
event timing transcript
    +
session nonce
    ↓
BLAKE2b / SHA-256
    ↓
draw stream
```

The result should be:

- unpredictable;
- unbiased across 78 cards;
- testable;
- implementation-versioned.

Do not use `random.random()` as the production entropy source.

---

## 7.3 Unbiased selection

Do not select the card using naïve modulo arithmetic unless the input range is constructed so modulo bias is impossible.

Use either:

- a standard cryptographic `randbelow(78)` implementation; or
- rejection sampling from the derived cryptographic byte stream.

The wheel-generated entropy must actually contribute to the final derived state rather than being merely cosmetic.

---

## 7.4 Draw commitment

Once the card is resolved:

1. immediately write the immutable oracle portion of the reading to the database;
2. then begin visual reveal;
3. then retrieve knowledge;
4. then call the interpretation backend.

If the program crashes after the draw but before generation, restarting should recover the same day's card.

There must be no failure path that silently redraws.

---

# 8. Tarot Model

## 8.1 Deck

Use the complete 78-card Crowley-Harris Thoth structure:

- 22 Major Arcana;
- 56 Minor Arcana;
- Wands;
- Cups;
- Swords;
- Disks;
- Thoth court structure:
  - Knight;
  - Queen;
  - Prince;
  - Princess.

Use Crowley's card names where they differ from common Rider-Waite-Smith nomenclature, including names such as:

- Adjustment;
- Lust;
- Art;
- Fortune;
- The Aeon;
- The Universe.

No reversals in v0.1.

---

## 8.2 Canonical deck metadata

Store authoritative application metadata separately from the Book of Thoth text corpus.

Suggested resource:

```text
src/syzygy/resources/thoth_deck.yaml
```

Each card should have a stable machine ID.

Example schema:

```yaml
id: two_of_wands
display_name: Dominion
full_name: Two of Wands - Dominion
arcana: minor
suit: wands
rank: 2
court: null
element: fire
astrology:
  planet: Mars
  sign: Aries
  decan:
    start_degree: 0
    end_degree: 10
qabalah:
  sephira: Chokmah
book_of_thoth_aliases:
  - Two of Wands
  - Dominion
```

Major and court cards will have different applicable metadata.

Fields may be null where a correspondence does not apply.

This file is canonical program data and should be manually checked against reliable Thoth references. Do not generate it automatically from model memory.

---

## 8.3 Artwork

Do not bundle scans or reproductions of Frieda Harris's Thoth card artwork unless the project has clear legal rights to distribute them.

v0.1 should use original terminal-native representations:

- card frame;
- Roman numeral or rank;
- title;
- suit symbol;
- planetary/zodiacal glyphs;
- abstract custom geometry;
- procedural decorative motifs.

The goal is recognizably **Syzygy**, not an ASCII photocopy of the physical deck.

---

# 9. Astrology Engine

## 9.1 Selected abstraction

Create an internal astrology protocol so the rest of the app never depends directly on one third-party library's data model.

```python
class AstrologyEngine(Protocol):
    def calculate_natal(self, birth: BirthData) -> NatalChart: ...
    def calculate_transits(
        self,
        natal: NatalChart,
        instant: datetime,
    ) -> TransitSnapshot: ...
```

The initial implementation is expected to use Kerykeion.

Keep the adapter boundary clean enough that a lower-level ephemeris engine can replace it later without rewriting the TUI, database, prompt builder, or archive.

---

## 9.2 Zodiac and house assumptions

v0.1 defaults:

- tropical zodiac;
- apparent geocentric perspective;
- Placidus natal houses;
- exact birthplace coordinates;
- correct IANA birth timezone.

House-system choice should be stored on the profile.

Do not silently reinterpret an existing chart if defaults change later.

---

## 9.3 Bodies used

v0.1 transit analysis should consider:

- Sun;
- Moon;
- Mercury;
- Venus;
- Mars;
- Jupiter;
- Saturn;
- Uranus;
- Neptune;
- Pluto.

Natal targets may additionally include:

- Ascendant;
- Midheaven.

Do not include dozens of asteroids, Lilith variants, fixed stars, hypothetical points, or minor bodies in v0.1.

More data is not necessarily more meaningful.

---

## 9.4 Aspects used

v0.1 uses only major aspects:

- conjunction;
- opposition;
- square;
- trine;
- sextile.

No quintiles or minor aspects in the canonical daily context.

Syzygy should own its transit policy instead of accepting broad library defaults.

Initial transit orb policy:

| Aspect | Maximum orb |
|---|---:|
| Conjunction | 3.0° |
| Opposition | 3.0° |
| Square | 3.0° |
| Trine | 3.0° |
| Sextile | 2.0° |

Additional constraints:

- natal Ascendant/MC aspects: maximum 2.0°;
- transiting Moon aspects: maximum 1.5°;
- exact values and applying/separating state are preserved;
- this policy is configuration data and must be versioned.

The point is not to claim a uniquely correct astrological doctrine. The point is to avoid flooding the model with weak aspects.

---

## 9.5 Transit significance

The LLM should not receive every possible aspect equally.

Create a deterministic `TransitRanker`.

A possible initial score:

```text
score =
    aspect_weight
  × orb_closeness
  × transiting_body_weight
  × natal_target_weight
  × applying_modifier
```

The exact weights should be explicit configuration, not hidden prompt intuition.

Suggested behavior:

- tighter aspects rank higher;
- conjunction/opposition/square receive slightly more salience than sextile;
- aspects to Sun, Moon, Ascendant, and personal planets rank strongly;
- slow-planet contacts to personal natal points rank strongly;
- applying aspects may receive a small boost;
- Moon contacts should be allowed to surface but should not crowd out every slower transit.

Select roughly the top 3-6 meaningful transit aspects for interpretation.

Always retain the complete transit snapshot in the saved reading, even if only a subset is sent to the LLM.

---

# 10. Current Time and Daily Identity

Use Python's standard time facilities:

- timezone-aware `datetime`;
- `zoneinfo`;
- UTC for storage;
- system local timezone for determining the local date of consultation.

Each reading stores:

- local calendar date;
- local timezone at consultation;
- exact UTC timestamp;
- exact local timestamp.

The unique daily constraint is:

```text
(profile_id, consultation_local_date)
```

A user traveling between timezones may therefore create a reading according to the calendar date observed by their machine at first consultation.

Do not request current GPS/location simply to determine “today.”

For deterministic tests and debugging, allow an injected clock.

Example:

```bash
syzygy today --at "2026-08-07T08:00:00-04:00"
```

This should be explicitly marked as a development/debug feature if exposed in release builds.

---

# 11. Book of Thoth Knowledge System

## 11.1 Source policy

The user's copy of *The Book of Thoth* is an input to a local preprocessing pipeline.

The repository should **not** contain the complete book text unless distribution rights are clearly established.

The application should not require users to upload the book to a cloud service.

Default flow:

```bash
syzygy knowledge ingest "/path/to/Book of Thoth.pdf"
```

The resulting local knowledge database is private application data.

Store the source file hash so the application can detect whether an indexed source changed.

Do not retain extracted temporary files unnecessarily.

---

## 11.2 Do not begin with blind vector chunking

This corpus has strong known structure.

When the drawn card is The Hermit, the program already knows that the section specifically discussing The Hermit is primary evidence.

Therefore retrieval has two tiers.

### Tier 1: deterministic structural retrieval

Always retrieve:

- the section directly corresponding to the drawn card;
- applicable general material for that card class;
- relevant passages explicitly associated with its astrological correspondence, when indexed.

This is the authoritative base context.

### Tier 2: semantic retrieval

Optionally retrieve a small number of related passages based on the actual Syzygy:

- card;
- card correspondence;
- significant current transits;
- relevant natal placements;
- symbolic tensions identified by deterministic metadata.

Embeddings enhance context. They do not replace exact card lookup.

---

## 11.3 Ingestion pipeline

Suggested stages:

```text
PDF
 ↓
text-layer extraction
 ↓
page-aware normalization
 ↓
section detection
 ↓
card-section mapping
 ↓
chunking within semantic sections
 ↓
metadata assignment
 ↓
SQLite full-text index
 ↓
optional embedding index
```

### Step 1: extraction

Prefer the PDF text layer.

Use a library such as PyMuPDF for page-aware extraction.

OCR should only be a fallback for pages whose text layer is absent or unusable.

Keep page numbers attached to extracted content.

### Step 2: normalization

Normalize:

- repeated headers;
- repeated footers;
- page numbers accidentally embedded in prose;
- line-wrap hyphenation;
- excessive whitespace;
- obvious scan artifacts.

Do not aggressively rewrite punctuation or spelling. Crowley's terminology matters.

### Step 3: section segmentation

Identify:

- front matter;
- general theory;
- Major Arcana sections;
- court-card sections;
- suit discussions;
- numbered Minor Arcana sections;
- appendices/tables;
- astrology/Qabalah/alchemy discussions.

### Step 4: card mapping

Map headings and aliases to canonical `card_id`.

Do not rely only on semantic similarity when a section can be structurally identified.

### Step 5: chunking

Chunk **inside semantic sections**, never blindly across section boundaries.

Target moderate chunks, for example roughly 600-1,200 tokens, with small overlap only when needed.

A complete short card section may remain a single chunk.

### Step 6: metadata

Example:

```json
{
  "source": "book_of_thoth",
  "source_hash": "...",
  "section_id": "minor_wands_02",
  "card_id": "two_of_wands",
  "section_type": "card",
  "title": "Two of Wands - Dominion",
  "page_start": 181,
  "page_end": 182,
  "chunk_index": 0,
  "text": "..."
}
```

### Step 7: index

v0.1 should implement:

- exact metadata lookup;
- SQLite full-text search.

Embeddings are useful but not required to ship the first working end-to-end reading.

Add semantic embeddings after deterministic retrieval is working and evaluated.

---

## 11.4 Embedding architecture

When added, embeddings should be optional and local by default.

Do not require a hosted vector database.

The corpus is tiny enough for a local index.

Possible implementations:

- SQLite vector extension;
- a small on-disk vector matrix plus cosine search;
- another lightweight embedded vector mechanism.

The interface should be abstract:

```python
class SemanticIndex(Protocol):
    def index(self, chunks: list[KnowledgeChunk]) -> None: ...
    def search(self, query: str, k: int) -> list[KnowledgeHit]: ...
```

Do not couple ingestion to one embedding model.

Store:

- embedding model identifier;
- vector dimension;
- index version;
- source hash.

If the embedding model changes, rebuild the vector index rather than pretending vectors from different models are compatible.

---

# 12. Interpretation Context Builder

The context builder is where much of Syzygy's intelligence should live.

Its job is to give the model enough high-quality information to reason well without drowning it in the full chart and full book.

Conceptual pipeline:

```text
Drawn card
   │
   ├── canonical metadata
   └── direct Book of Thoth section
                │
Current transits│
   │            │
   └── rank significant aspects
                │
Natal chart─────┤
                │
Card correspondence
   └── identify relevant natal placements/transits
                │
         optional semantic retrieval
                │
                ▼
        InterpretationContext
```

---

## 12.1 Always include

- profile display name;
- consultation date/time;
- drawn card;
- canonical card correspondences;
- direct Book of Thoth card section or relevant chunks;
- ranked significant transit-to-natal aspects;
- natal placements directly touched by those aspects;
- Sun;
- Moon;
- Ascendant;
- prompt/version metadata.

---

## 12.2 Conditionally include

If the card has a planetary attribution:

- natal placement of that planet;
- significant current transits involving that planet.

If the card has a zodiacal attribution:

- natal planets in that sign;
- the natal house containing that sign if useful;
- current planets in that sign if directly relevant.

If the card represents a decan:

- explicitly include the planet/sign combination;
- prioritize resonant transit data.

If related source retrieval returns strong passages:

- include only the top few;
- preserve source/page metadata.

---

## 12.3 Do not include by default

- the entire natal chart serialization;
- every transit;
- every aspect;
- every minor body;
- the entire Book of Thoth;
- previous daily readings.

Today's reading must stand on today's Self + Cosmos + Chance.

History belongs to a separate analysis mode.

---

# 13. LLM Architecture

## 13.1 Provider protocol

```python
class InterpretationProvider(Protocol):
    provider_id: str
    model_id: str

    async def interpret(
        self,
        context: InterpretationContext,
    ) -> InterpretationResult: ...
```

Implementations:

```text
llm/
├── base.py
├── context_builder.py
├── schemas.py
└── providers/
    ├── local_llama.py
    ├── openai.py
    └── anthropic.py
```

The rest of the application should not care which provider is active.

---

## 13.2 Local inference

Prefer interoperability with `llama.cpp`.

The cleanest v0.1 integration is likely an OpenAI-compatible local HTTP endpoint exposed by `llama-server`, with optional process management added later.

Advantages:

- model runtime is isolated from the Python application;
- Syzygy does not need to compile a heavy inference binding into every package;
- users can point Syzygy at an already-running local server;
- provider logic resembles remote API adapters.

The app may later offer:

```text
[M] Manage local model
```

but model download/setup is not required for the initial architecture.

---

## 13.3 Remote inference

Support optional hosted providers.

API keys:

- never stored in the Syzygy SQLite database;
- never printed;
- never logged;
- preferably stored in the OS keyring;
- environment-variable fallback is acceptable.

The provider adapter must send only the information needed for the reading.

If a user selects a remote provider, clearly communicate that the interpretation context is leaving the local machine.

---

## 13.4 Structured model output

Do not accept unconstrained prose as the internal output format.

Require a schema similar to:

```json
{
  "alignment_title": "string",
  "esoteric": {
    "summary": "string",
    "body": "string"
  },
  "conventional": {
    "summary": "string",
    "body": "string",
    "watch_for": ["string"],
    "reflection": "string"
  },
  "source_chunk_ids": ["string"]
}
```

Validate with Pydantic.

If validation fails:

1. retry once with a repair instruction;
2. if it still fails, preserve the oracle state and show a recoverable interpretation error;
3. never redraw the card.

---

## 13.5 Prompt rules

The system prompt should enforce:

- interpret only supplied astrological facts;
- never invent placements, aspects, houses, or card correspondences;
- use Crowley source material as the principal Thoth reference;
- paraphrase source material rather than reproducing long passages;
- clearly distinguish observation from symbolic interpretation;
- do not present generated divination as factual certainty about future events;
- do not make medical, legal, financial, or safety-critical predictions;
- do not claim Buddhist doctrinal authority;
- make the Esoteric and Conventional sections consistent with one another;
- keep the reading concise enough to remain a daily ritual rather than an essay.

The model may identify symbolic resonance. It may not rewrite the oracle inputs to create better resonance.

---

# 14. Reading Output

The reading screen should reveal information in stages.

Suggested sequence:

1. card reveal;
2. card title and correspondence;
3. significant transit glyphs attach around the card;
4. `SELF`, `COSMOS`, and `CHANCE` visually align;
5. interpretation begins;
6. reading appears.

Example:

```text
┌─────────────────────────────────────────────────────────────┐
│                           SYZYGY                            │
│                                                             │
│                    ┌─────────────────┐                      │
│                    │       IX        │                      │
│                    │                 │                      │
│                    │   THE HERMIT    │                      │
│                    │                 │                      │
│                    │      VIRGO      │                      │
│                    └─────────────────┘                      │
│                                                             │
│       ♄ □ ♀  0°48'                         ♂ △ ☉  1°12'     │
│                                                             │
│ SELF                  COSMOS                  CHANCE        │
│  ●──────────────────────●──────────────────────●           │
│                                                             │
│ [1] ESOTERIC      [2] CONVENTIONAL      [I] INPUTS         │
└─────────────────────────────────────────────────────────────┘
```

---

## 14.1 Esoteric view

The Esoteric view may discuss:

- the card's specific Thoth symbolism;
- astrological correspondence;
- relationship to today's major transits;
- natal resonances;
- Thelemic/Hermetic/Qabalistic/alchemical interpretation where supported.

It should assume an interested reader rather than explain every occult term from first principles.

---

## 14.2 Conventional view

The Conventional view translates the same alignment into ordinary language.

Suggested structure:

```text
TODAY

2-4 paragraphs of plain-language interpretation.

WATCH FOR
• ...
• ...

REFLECT
One concrete question.
```

Avoid generic positivity.

The Conventional section should be able to say that the day's pattern suggests friction, uncertainty, delay, intensity, or restraint when that is genuinely the interpretation.

It should not turn every card into self-help encouragement.

---

## 14.3 Inspect inputs

The user must be able to inspect exactly what the model was given.

Example:

```text
[I] INPUTS
```

shows:

- card;
- card metadata;
- selected transits with orbs;
- relevant natal placements;
- Book of Thoth source sections/pages;
- provider/model;
- prompt version.

This is important for trust, debugging, and the project's programmer-oriented identity.

---

# 15. History and Archive

Every canonical daily reading is retained.

The archive is not merely a list of generated prose. It stores enough structured information for future analysis.

Example screen:

```text
SYZYGY // ARCHIVE

Readings                         183
Major Arcana                      47
Minor Arcana                     136

SUITS
Wands                             32
Cups                              38
Swords                            31
Disks                             35

Most drawn
The Hermit                         6
Adjustment                         5
Six of Swords - Science            5
```

All statistics are descriptive.

Do not imply that frequency deviations are statistically meaningful or evidence of supernatural causation.

---

## 15.1 History analysis

A future command may support:

```text
syzygy reflect month
syzygy reflect card hermit
syzygy reflect transit saturn
```

This is explicitly separate from the daily reading.

History analysis may use:

- structured historical reading data;
- aggregate counts;
- selected previous interpretations;
- recurring transit patterns;
- card frequencies.

Today's oracle must never be conditioned on previous readings unless the user intentionally invokes an analysis feature.

---

# 16. Storage

Use SQLite.

Suggested default location via `platformdirs`, not hard-coded Unix-only paths.

Conceptual data directory:

```text
syzygy/
├── syzygy.db
├── knowledge/
│   └── ...
├── models/
│   └── ...
└── logs/
    └── ...
```

Do not use cloud storage in v0.1.

---

## 16.1 Tables

### `profiles`

```text
id
name
birth_date
birth_time
birth_place_label
birth_latitude
birth_longitude
birth_timezone
house_system
zodiac_type
astrology_engine
astrology_engine_version
chart_schema_version
natal_chart_json
created_at
updated_at
```

### `readings`

```text
id
profile_id
consultation_local_date
consultation_local_timestamp
consultation_utc_timestamp
consultation_timezone

card_id
sortes_version
entropy_digest

astrology_policy_version
transit_snapshot_json
selected_transits_json
interpretation_context_json

provider_id
model_id
prompt_version
interpretation_json
interpretation_status

created_at
updated_at
```

Constraint:

```text
UNIQUE(profile_id, consultation_local_date)
```

### `knowledge_sources`

```text
id
source_type
title
file_hash
ingestion_version
created_at
```

### `knowledge_chunks`

```text
id
source_id
section_id
section_type
card_id
title
page_start
page_end
chunk_index
text
text_hash
```

Optional later:

### `knowledge_embeddings`

```text
chunk_id
embedding_model
embedding_version
vector
```

---

## 16.2 Migration strategy

Use simple explicit SQLite schema migrations.

For a small local application, avoid introducing an ORM solely for migrations unless implementation complexity later justifies it.

Every stored opaque JSON structure must include or inherit a schema version.

Never silently destroy old readings during migrations.

---

# 17. Privacy

Syzygy handles personally identifying birth information.

Rules:

- local storage by default;
- no analytics/telemetry by default;
- no cloud account;
- no automatic synchronization;
- no current location collection in v0.1;
- API keys stored outside the database;
- remote LLM usage must be visibly identified;
- logs must not dump full profile records or API payloads by default.

Add:

```bash
syzygy export profile
syzygy delete profile
```

eventually, with clear behavior.

A future privacy option may retain only the calculated natal chart and discard original birth inputs, but v0.1 stores the birth inputs so charts can be audited and deliberately recalculated.

---

# 18. Visual Design Language

## 18.1 General

Use Textual for the TUI.

The interface should be custom rather than a collection of stock widgets.

Textual provides the application shell, layout, event system, styling, workers, and testability. Syzygy supplies the visual identity.

---

## 18.2 Balatro influence

Borrow principles, not assets:

- one strong focal object;
- card-centered composition;
- tactile keypress feedback;
- fast reveal sequencing;
- animated state changes;
- dense but readable status information;
- modifiers visually attaching to a central card;
- subtle jitter, pulse, or distortion;
- deliberate use of terminal color.

Do not reproduce Balatro's card frames, exact CRT shader, fonts, Joker presentation, UI layout, or proprietary art.

---

## 18.3 Original Syzygy motifs

Primary motifs:

- wheel;
- alignment;
- three bodies;
- orbital lines;
- crosshairs;
- planetary glyphs;
- zodiac glyphs;
- alchemical symbols;
- rays;
- geometric seals;
- terminal noise collapsing into order.

The central animation language should repeatedly transform:

```text
CHAOS → MOTION → DRAW → ALIGNMENT
```

---

## 18.4 Color

Use a limited original palette.

The aesthetic should work in:

1. truecolor terminals;
2. 256-color terminals;
3. reduced-color fallback.

Never make color the only carrier of meaning.

Avoid a generic purple/blue “mystical app” palette.

A productive direction is:

- near-black field;
- warm bone/parchment text;
- solar gold;
- oxidized red;
- lunar/cold blue;
- one high-energy accent for chance/reveal.

Exact colors should be explored visually rather than treated as product architecture.

---

## 18.5 Typography and glyphs

Use terminal-native text.

Preferred:

- box-drawing characters;
- Unicode planetary/zodiac glyphs;
- block elements;
- Braille patterns where useful;
- ASCII fallbacks.

The UI must survive fonts that lack specialized occult symbols.

Create a glyph capability/fallback layer rather than scattering Unicode assumptions through views.

---

## 18.6 Responsive terminal behavior

Define minimum supported dimensions.

Suggested initial targets:

- ideal: 100×32 or larger;
- compact: 80×24;
- below minimum: show a clean “terminal too small” state.

Do not let complex card art make the application unusable at common terminal sizes.

---

# 19. TUI Screens

Suggested structure:

```text
tui/
├── app.py
├── screens/
│   ├── welcome.py
│   ├── profile_create.py
│   ├── profile_select.py
│   ├── home.py
│   ├── wheel.py
│   ├── reveal.py
│   ├── reading.py
│   ├── chart.py
│   ├── archive.py
│   ├── knowledge.py
│   └── settings.py
├── widgets/
│   ├── wheel.py
│   ├── tarot_card.py
│   ├── alignment.py
│   ├── transit_badge.py
│   ├── glyph.py
│   └── reading_panel.py
└── syzygy.tcss
```

Long-running operations such as LLM inference must run through worker/background-task facilities so terminal animation and cancellation remain responsive.

---

# 20. CLI

The TUI is primary, but a scriptable CLI makes the architecture testable and useful.

Suggested commands:

```bash
syzygy
syzygy today
syzygy chart
syzygy archive

syzygy profile list
syzygy profile create
syzygy profile show <name>
syzygy profile recalculate <name>

syzygy knowledge status
syzygy knowledge ingest <pdf>

syzygy model status
syzygy model configure

syzygy doctor
```

Useful development commands:

```bash
syzygy dev draw --seed ...
syzygy dev context --date ...
syzygy dev astrology --at ...
```

Production drawing must never use a fixed test seed accidentally.

---

# 21. Suggested Python Package Structure

```text
.
├── DESIGN.md
├── README.md
├── LICENSE
├── pyproject.toml
├── src/
│   └── syzygy/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── clock.py
│       │
│       ├── domain/
│       │   ├── profile.py
│       │   ├── astrology.py
│       │   ├── tarot.py
│       │   ├── knowledge.py
│       │   └── reading.py
│       │
│       ├── astrology/
│       │   ├── base.py
│       │   ├── kerykeion_backend.py
│       │   ├── policy.py
│       │   └── ranking.py
│       │
│       ├── sortes/
│       │   ├── entropy.py
│       │   ├── deck.py
│       │   └── draw.py
│       │
│       ├── knowledge/
│       │   ├── ingest.py
│       │   ├── normalize.py
│       │   ├── segment.py
│       │   ├── store.py
│       │   ├── retrieve.py
│       │   └── embeddings.py
│       │
│       ├── interpretation/
│       │   ├── base.py
│       │   ├── context_builder.py
│       │   ├── prompts.py
│       │   ├── schemas.py
│       │   └── providers/
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
    ├── fixtures/
    ├── astrology/
    ├── sortes/
    ├── knowledge/
    ├── interpretation/
    ├── storage/
    └── tui/
```

Keep domain models independent from Textual widgets and third-party provider response types.

---

# 22. Initial Dependencies

Likely core dependencies:

```text
textual
pydantic
kerykeion
platformdirs
PyMuPDF
```

Likely optional dependencies:

```text
keyring
httpx
timezonefinder
geopy
```

Semantic retrieval may later add an embedding package or lightweight vector extension.

Do not add LangChain, LlamaIndex, a hosted vector database, a web framework, or a general agent framework unless the project develops a concrete need for one.

The retrieval and orchestration problem is small enough to remain explicit.

### Licensing note

The initial astrology backend selection creates a licensing constraint that must be respected by the repository. The current design assumes an open-source distribution compatible with the selected astrology library. If the desired repository license is incompatible, resolve that **before** building application code deeply around the backend.

Also independently review redistribution rights for:

- *The Book of Thoth* text;
- Crowley-Harris Thoth card artwork;
- any future model weights.

The safe v0.1 default is to distribute neither the book text nor deck artwork.

---

# 23. Error Handling

## Astrology calculation failure

Do not continue to a draw if the Self/Cosmos state cannot be calculated.

Show the exact failing input and preserve profile data for correction.

---

## Knowledge unavailable

A reading may still be drawn.

If the Book of Thoth corpus is not installed, Syzygy may either:

1. show the card + astrology without LLM interpretation; or
2. use only canonical deck metadata and clearly label the reduced context.

Never silently imply Crowley grounding when the source corpus was unavailable.

---

## LLM unavailable

The reading remains valid.

Show:

```text
THE ALIGNMENT IS FIXED.
INTERPRETATION IS UNAVAILABLE.

[R] Retry interpretation
[I] Inspect inputs
```

Retrying must use the same card and astrology snapshot.

---

## Invalid LLM output

Retry schema repair once.

If unsuccessful, save error state and allow later retry.

Never discard or redraw.

---

# 24. Versioning and Provenance

Every reading should be reproducible as a historical artifact even if prose generation itself is stochastic.

Store:

- Syzygy app version;
- profile/chart schema version;
- astrology engine/version;
- astrology policy version;
- Sortes algorithm version;
- card ID;
- entropy digest;
- knowledge source hash;
- knowledge ingestion version;
- source chunk IDs;
- model provider;
- model ID;
- prompt version;
- structured interpretation.

This makes old readings inspectable after the application evolves.

---

# 25. Testing Strategy

## 25.1 Astrology

Create fixed test fixtures for several known birth charts.

Test:

- planetary longitudes within a defined tolerance;
- Ascendant/MC;
- house cusps;
- timezone/DST handling;
- transit aspects;
- applying/separating state where supported.

Where possible, compare fixtures against an independent trusted ephemeris rather than merely snapshotting the same library's output.

Test at least one DST boundary and one birthplace outside the United States.

---

## 25.2 Current-location invariance

Because v0.1 claims not to need current location, explicitly test this architectural assumption.

For the same UTC instant:

- calculate geocentric current planetary positions using multiple arbitrary locations if required by the backend API;
- verify the positions used by Syzygy are invariant within tolerance;
- ensure current houses/angles are excluded.

This prevents accidental dependence on a dummy transit location.

---

## 25.3 Sortes

Test:

- deterministic output when a test seed is injected;
- all 78 cards reachable;
- rejection sampler correctness;
- approximate uniformity across large test runs;
- no production path uses the deterministic test RNG;
- user event entropy changes derived output;
- OS entropy is always mixed in for production.

Statistical tests should catch obvious implementation bias, not attempt to prove metaphysical randomness.

---

## 25.4 Daily locking

Test:

1. first draw creates a reading;
2. second request that day returns it;
3. interpretation failure does not permit redraw;
4. restart after card commitment recovers the card;
5. next local calendar day allows a new draw.

---

## 25.5 Knowledge retrieval

For every card:

- exact card lookup returns at least one appropriate source chunk after valid ingestion;
- card aliases resolve correctly;
- chunks retain page metadata;
- no chunk crosses unrelated card sections;
- deterministic retrieval always outranks semantic retrieval.

Create golden tests for several cards from different parts of the deck.

---

## 25.6 Interpretation

Use mocked providers.

Test that context contains:

- the exact card;
- correct selected transits;
- relevant natal placements;
- direct source chunks.

Test that it does **not** contain:

- previous readings;
- unrelated private profile fields;
- current location;
- API keys.

Snapshot the structured prompt payload by `prompt_version`.

---

## 25.7 Storage

Test migrations on old fixture databases.

Test uniqueness of one reading per profile/day.

Test deletion and export once those commands exist.

---

## 25.8 TUI

Use Textual's testing facilities for:

- profile creation;
- daily reading state transitions;
- wheel event flow;
- reading recovery;
- resize behavior;
- keyboard navigation.

Visual snapshot testing is desirable for major screens once the design stabilizes.

---

# 26. Performance and Responsiveness

Targets for non-LLM operations:

- application shell should feel immediate;
- profile loading should be effectively instant;
- natal/transit calculation should not visibly stall the interface;
- random draw should resolve immediately after commitment;
- archive browsing should be local and fast.

LLM inference is the only operation expected to take materially longer.

All inference and heavyweight ingestion work must be asynchronous relative to the TUI.

Animation must continue while waiting for a model.

---

# 27. Observability

No telemetry by default.

Local debug logging may include:

- component;
- event;
- timings;
- model/provider name;
- chunk IDs;
- error traces.

It must not include by default:

- API keys;
- full birth profile;
- raw Book of Thoth chunks;
- complete remote provider payloads;
- raw entropy event transcript.

Add a `--debug` mode rather than noisy normal logs.

---

# 28. Security

This is not a high-risk security application, but basic hygiene matters.

- use OS CSPRNG;
- validate all model output;
- parameterize SQLite queries;
- treat PDF ingestion as untrusted input;
- do not execute content extracted from the PDF;
- do not interpolate model output into shell commands;
- escape/handle terminal control characters in ingested text;
- do not expose API keys in diagnostics;
- limit local model/server binding to localhost by default.

---

# 29. Interpretation Tone

Generated prose should feel serious without pretending certainty.

Desired qualities:

- precise;
- symbolically literate;
- concise;
- occasionally strange;
- comfortable with tension and ambiguity;
- grounded in supplied material;
- free of generic motivational language.

Avoid:

- “The universe is telling you…”
- “This is definitely going to happen…”
- faux-ancient prose;
- excessive disclaimers inside every reading;
- therapeutic clichés;
- generic affirmation language;
- flattening every difficult symbol into a positive lesson.

The reader should feel that a specific symbolic configuration was interpreted, not that a horoscope template was filled in.

---

# 30. v0.1 Scope

v0.1 is complete when a new user can:

1. install Syzygy;
2. create and save a profile;
3. resolve birthplace coordinates/timezone;
4. calculate and save an accurate natal chart;
5. ingest their local *Book of Thoth* PDF;
6. open the TUI on a day with no reading;
7. see current transit context calculated;
8. turn the Wheel;
9. draw exactly one unbiased card from all 78 Thoth cards;
10. have the card committed to storage;
11. build a grounded interpretation context;
12. generate Esoteric + Conventional interpretations through at least one model provider;
13. inspect the inputs used for interpretation;
14. reopen the same day's reading without rerolling;
15. browse previous readings.

Everything else is secondary.

---

# 31. Explicitly Out of Scope for v0.1

Do not build yet:

- web app;
- mobile app;
- account system;
- cloud sync;
- social sharing;
- subscriptions;
- gamification;
- streaks;
- achievements;
- card rarity;
- multiple-card spreads;
- reversed cards;
- alternative decks;
- I Ching;
- runes;
- KJV word oracle;
- freeform chat with the oracle;
- current-location astrology;
- relocated houses;
- astrocartography;
- synastry;
- solar return reports;
- push notifications;
- automatic daily generation;
- agent framework;
- hosted backend;
- hosted vector database.

Some may become good later features. None should delay a working daily Syzygy.

---

# 32. Implementation Milestones

## Milestone 0 - Repository skeleton

Deliver:

- `pyproject.toml`;
- package layout;
- formatting/linting/test config;
- basic CLI entry point;
- SQLite initialization;
- placeholder Textual app;
- `DESIGN.md`.

Acceptance:

```bash
syzygy
pytest
```

both run successfully.

---

## Milestone 1 - Domain models and Thoth deck

Deliver:

- Pydantic domain schemas;
- canonical 78-card deck file;
- deck loader/validator;
- tests proving exactly 78 unique card IDs;
- no reversals.

Acceptance:

```bash
syzygy dev deck
```

can enumerate the canonical deck.

---

## Milestone 2 - Astrology

Deliver:

- profile model;
- birthplace resolution;
- astrology protocol;
- Kerykeion adapter;
- natal calculation;
- saved natal chart;
- current transit calculation;
- Syzygy aspect policy;
- transit ranking;
- validation fixtures.

Acceptance:

```bash
syzygy profile create
syzygy chart
syzygy dev astrology
```

produce stable structured data.

Do not start LLM work until this layer is trustworthy.

---

## Milestone 3 - Sortes

Deliver:

- entropy collector abstraction;
- production CSPRNG mixing;
- wheel-event entropy input;
- unbiased 78-card draw;
- injectable deterministic test source;
- algorithm versioning.

Acceptance:

- statistical tests pass;
- fixed test seed is reproducible;
- production draw cannot be accidentally seeded from CLI test options.

---

## Milestone 4 - Daily reading state machine and storage

Deliver:

- `readings` persistence;
- unique daily constraint;
- immutable card commitment;
- recovery after simulated crash;
- reading state enum:
  - `PREPARED`;
  - `DRAWN`;
  - `CONTEXT_READY`;
  - `INTERPRETING`;
  - `COMPLETE`;
  - `INTERPRETATION_FAILED`.

Acceptance:

A test can kill the flow after `DRAWN`, restart, and prove the same card survives.

---

## Milestone 5 - TUI ritual

Deliver:

- profile picker;
- home screen;
- Wheel widget;
- entropy interaction;
- reveal screen;
- basic card terminal art;
- alignment animation;
- existing-reading flow.

Do not integrate a real model yet. Use fixture interpretation text.

Acceptance:

The complete daily ritual feels coherent using fake interpretation data.

This is important: UX should not depend on model work being finished.

---

## Milestone 6 - Book of Thoth ingestion

Deliver:

- PDF text extraction;
- normalization;
- section/chunk model;
- source/page preservation;
- manual mapping/override tools;
- exact card retrieval;
- FTS search;
- ingestion diagnostics.

Acceptance:

For representative cards from Major, Minor, and Court categories, the application retrieves the correct primary source material without embeddings.

---

## Milestone 7 - Interpretation

Deliver:

- context builder;
- structured output schema;
- prompt versioning;
- local provider adapter;
- at least one remote provider adapter;
- provider configuration;
- schema retry/repair;
- input inspector.

Acceptance:

The same immutable reading can be interpreted by two providers without changing its card or astrology snapshot.

---

## Milestone 8 - Archive

Deliver:

- reading list;
- reading detail;
- card/suit counts;
- basic transit filters;
- reopening past readings.

No LLM trend analysis is required for v0.1.

---

## Milestone 9 - Polish and release

Deliver:

- original visual theme;
- compact terminal mode;
- glyph fallbacks;
- startup/doctor checks;
- documentation;
- license review;
- clean install process;
- no dependency on developer machine state.

---

# 33. Definition of Done

Syzygy v0.1 should satisfy these invariants:

### Oracle invariants

- Astrology is calculated, never hallucinated.
- The card is selected randomly, never chosen by the LLM.
- Every card is equally likely.
- The draw uses all 78 Thoth cards.
- Cards are upright only.
- One canonical reading exists per profile/day.
- A failed interpretation cannot cause a redraw.

### Knowledge invariants

- The direct Book of Thoth section for the drawn card is preferred over semantic similarity.
- Source/page metadata survives ingestion.
- The book itself is not bundled by default.
- The model cannot silently invent canonical Thoth correspondences.

### Privacy invariants

- Profiles and readings are local by default.
- Current location is not required.
- Remote model use is explicit.
- API keys are not stored in the readings database.

### UX invariants

- The Wheel is a real interaction, not a themed “Randomize” button.
- The tarot card remains the visual focal point.
- Astrology behaves like modifiers/context around the card.
- The application feels game-like but has no game economy.
- The reading can be inspected down to its factual inputs.

### Architecture invariants

- TUI code does not own astrology logic.
- LLM providers do not own prompt/context selection.
- Third-party astrology types do not leak throughout the domain.
- Model/provider choice can change without changing oracle mechanics.
- Old readings remain meaningful after upgrades.

---

# 34. Guidance for Coding Agents

When implementing from this document:

1. **Do not reinterpret product decisions casually.**  
   Upright-only cards, one daily draw, local-first storage, no current location, and the separation between oracle and LLM are deliberate.

2. **Prefer explicit code over framework-heavy abstraction.**  
   This is a small application. Do not introduce an agent framework, dependency injection framework, hosted vector database, or microservices architecture.

3. **Build vertical slices.**  
   A working CLI profile → astrology → draw → persisted reading is more valuable than a beautiful unfinished abstraction layer.

4. **Make deterministic components testable before adding generation.**

5. **Never use the LLM as a substitute for missing domain logic.**  
   If code can calculate, validate, retrieve, rank, or look up a fact, code should do it.

6. **Preserve provenance.**  
   If a value may matter to a future interpretation, save the source/version that produced it.

7. **Do not silently expand occult doctrine.**  
   Canonical card correspondences should come from curated project data and source material, not model improvisation.

8. **Do not optimize prematurely for a future web application.**  
   Keep domain logic interface-independent, but build the TUI that exists now.

9. **Treat visual design as product behavior.**  
   The Wheel, reveal, and alignment sequence are not polish to be added at the end. Prototype them before final LLM integration.

10. **Keep the project weird.**  
    A technically correct astrology dashboard is a failure if it feels like SaaS. A beautiful random-card animation is also a failure if the underlying astrology, randomness, or source grounding is sloppy.

---

# 35. Final Product Model

At its simplest, Syzygy is this:

```text
                    ┌───────────────┐
                    │     SELF      │
                    │  natal chart  │
                    └───────┬───────┘
                            │
                            │
┌───────────────┐           │           ┌───────────────┐
│    COSMOS     │───────────●───────────│    CHANCE     │
│   transits    │         SYZYGY        │  Thoth card   │
└───────────────┘           │           └───────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │  KNOWLEDGE CONTEXT  │
                 │  Book of Thoth +    │
                 │  card metadata      │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │    INTERPRETER      │
                 │  local or remote    │
                 │        LLM          │
                 └──────────┬──────────┘
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
             ESOTERIC           CONVENTIONAL
              reading              reading
                  \                   /
                   \                 /
                    └───────┬───────┘
                            ▼
                         ARCHIVE
```

The machine calculates what can be calculated, leaves chance to chance, and uses the model only where interpretation is actually required.

That is the core of the project.

---

# 36. Successor Notes — M19 Oracle

M19 implements the “separate free-consultation mode” anticipated in section
5.3 as **The Oracle**. It does not revise the daily rite:

- `[O]` from home asks one user-authored question, turns the same unbiased
  78-card upright Wheel, and interprets that fixed card through the question.
- Oracle consultations live in `oracle_consultations`, not `readings`. They
  have no per-day uniqueness constraint and never touch the daily reading's
  canonical `(profile_id, consultation_local_date)` constraint.
- “Unlimited” means any number of distinct consultations, each with its own
  effort and draw. Within a consultation there is no reroll: draw commitment,
  failure, interruption, and retry obey a separate state machine equivalent to
  the daily one.
- SELF and the already-ranked COSMOS remain supporting context. The question
  and card dominate the answer. This is not horary astrology; no current
  location, current houses, Ascendant, or Midheaven is collected or inferred.
- The original question is length-capped and stored locally as typed. A
  control-stripped, whitespace-normalized copy is JSON-quoted as user data in
  `InterpretationContext`; it cannot alter the card, astrology, sources, or
  output schema. A hosted provider receives it when selected; a local or
  fixture provider keeps it on the machine.
- The result adds a direct question-facing reflection to the same esoteric and
  conventional registers. The prompt forbids medical, legal, financial, and
  safety-critical directives and dated predictions presented as fact.
- The archive lists daily readings and Oracle consultations together but
  distinguishes them visibly and reopens both from stored data only.

ADR 0006 records the decisions and the reason migration 7, rather than the
already-used migration 6, owns the new table.

---

# 37. Successor Notes — M20 I Ching

M20 makes the I Ching an alternative mode of the question-led Oracle, not an
extra object added to a Thoth consultation:

- The question screen chooses one oracle before the Wheel. A consultation has
  one upright Thoth card or one six-line I Ching cast, never both.
- The cast uses three equiprobable coins per line, bottom upward. Totals 6, 7,
  8, and 9 therefore occur with probabilities 1/8, 3/8, 3/8, and 1/8. The same
  `EntropyCollector` and rejection sampler used by Sortes supply chance.
- Old yin and old yang are changing lines. Their changes form a resulting
  hexagram, read as the direction of the original cast rather than a second
  independent oracle. With no changing lines, the primary hexagram stands.
- All 64 canonical entries in `resources/iching_legge.yaml` carry the King Wen
  number and pattern, name, trigrams, Judgment, Image, six line texts, and
  entry-level page citations to James Legge's 1882 translation. The model is
  never asked to recall or select any of those facts.
- `iching_consultations` and its own state machine commit the cast before
  astrology context or provider work. Failure, interruption, retry, archive
  reopening, and profile deletion preserve the same boundaries as M19.
- I Ching uses `iching-v1`, its own injection-resistant prompt contract. SELF
  and ranked COSMOS remain supporting context; the fixed cast and quoted
  question dominate.

ADR 0007 records the mechanical and compositional decisions. Migration 9 owns
the parallel storage table.
