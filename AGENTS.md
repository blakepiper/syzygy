# AGENTS.md — Syzygy operating manual

Compact, durable rules for any coding agent working in this repository.
This is not the design doc — read `DESIGN.md` for product intent and
rationale, and `IMPLEMENTATION_PLAN.md` for how a specific milestone
should be built. This file is what you should already have loaded before
touching code.

## The one-paragraph mental model

```
SELF (saved natal chart) + COSMOS (current transits) + CHANCE (one random
Thoth card) → SYZYGY → an LLM interprets the fixed result in two
registers (Esoteric, Conventional). The LLM never calculates astrology,
never selects or changes the card, and can never cause a reroll.
```

If a task you're given seems to require the model to decide a fact instead
of receiving one, stop and re-read `DESIGN.md` section 5.2 — that's almost
certainly a design violation, not a shortcut.

## Invariants you must not violate

- **The card is committed to storage immediately after the draw, before
  any LLM call.** A failed or retried interpretation must never redraw
  the card. See `syzygy.domain.reading.ReadingStatus` and
  `ALLOWED_TRANSITIONS` — that state machine is the enforcement point.
- **One canonical reading per `(profile_id, consultation_local_date)`,
  enforced by the database**, not just application logic — see the
  `UNIQUE` constraint in `syzygy.storage.migrations`. Do not add a code
  path that bypasses it.
- **Upright cards only.** There is no `orientation`/`reversed` field
  anywhere in `syzygy.domain.tarot`. Do not add one. Do not add reversal
  logic, multi-card spreads, or alternative decks — out of scope for v0.1
  (`DESIGN.md` section 31).
- **All 78 cards, equal probability, real entropy.** `syzygy.sortes.draw`
  uses OS randomness mixed with interaction entropy via rejection
  sampling — never `random.random()`, never plain modulo over a raw byte.
  Production code must never construct `EntropyCollector` with a
  non-default `os_random` — that parameter exists for tests only.
- **Kerykeion (and any future astrology backend) stays behind
  `syzygy.astrology.base.AstrologyEngine`.** No Kerykeion type, enum, or
  serialization shape may appear outside `syzygy.astrology`. Same rule for
  Textual types (stay inside `syzygy.tui`) and any LLM provider SDK
  objects (stay inside `syzygy.interpretation.providers`).
- **Syzygy owns transit significance, not the astrology library and not
  the LLM.** Orb filtering lives in `syzygy.astrology.policy`
  (implemented). Ranking lives in `syzygy.astrology.ranking` (not yet
  implemented — see `IMPLEMENTATION_PLAN.md` Milestone 2). The LLM
  receives only the already-ranked top few aspects, never the full
  snapshot and never a request to judge importance itself.
- **`InterpretationContext` is the entire input surface for a provider**
  (`syzygy.domain.interpretation`). A provider must never reach into the
  database, the profile, or the astrology engine on its own. If a fact
  needs to reach the model, it needs to be added to the context builder's
  output, not fetched ad hoc inside a provider.
- **No current-location astrology.** Nothing in `syzygy.domain.astrology`
  collects or uses a current latitude/longitude, current houses, or a
  current Ascendant/Midheaven. Only the natal chart uses birthplace.
- **Canonical Thoth card data comes from `src/syzygy/resources/thoth_deck.yaml`
  and `docs/book_of_thoth.pdf`, never from model memory.** If you think a
  correspondence in `thoth_deck.yaml` is wrong, verify it against the PDF
  (see `docs/THOTH_INGESTION_MAP.md` section 11 for the citation method
  already used, including two Thoth-specific traps: the Tzaddi/Heh swap on
  The Emperor/The Star, and the counter-elemental court-card decan spans)
  before changing it, and update the ingestion map's citation alongside
  the fix.
- **The knowledge base is multi-source, but only one source is canonical.**
  `docs/book_of_thoth.pdf` is Tier 0 — the only source `thoth_deck.yaml`
  is grounded against, and the only source `Milestone 6`'s deterministic
  card lookup must treat as authoritative. `docs/understanding_crowley_thoth_tarot.pdf`
  (DuQuette) and `docs/mirror_of_the_soul.pdf` (Ziegler) are Tier 1
  supplementary retrieval sources only — see `docs/KNOWLEDGE_SOURCES.md`.
  Never use a Tier 1 source to add, change, or "correct" an entry in
  `thoth_deck.yaml`.
- **Never commit source text from the three books — only citations and
  vectors.** The PDFs are gitignored (`docs/*.pdf`), but that alone is not
  the rule: chunked full text is in substance the book, whatever directory
  it lands in. What ships in `src/syzygy/resources/knowledge/` is
  per-chunk citations (page range, heading, hash, word count) plus a
  non-invertible `float32[256]` signature — never the passages, and never
  the FTS index, which *is* the text. See
  `docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`.
  Citation-only chunks must also never reach a provider: a citation under
  the prompt's "SOURCE PASSAGES" heading invites the model to invent what
  the page says, so `reading_service` filters on `KnowledgeChunk.has_text`.
- **No LangChain, LlamaIndex, hosted vector DB, agent framework, dependency
  injection container, or web framework.** If you think you need one,
  you're probably over-engineering a small local app — re-read
  `ARCHITECTURE_HANDOFF.md` section 11 first.
- **Every dependency must be AGPL-3.0 compatible** (permissive licenses are
  always fine; other copyleft licenses need review) — see
  `docs/adr/0001-agpl-license-for-kerykeion.md`.

## Repository map

| Path | What lives here |
|---|---|
| `DESIGN.md` | Product design and rationale — read when product intent is unclear |
| `IMPLEMENTATION_PLAN.md` | Concrete architecture per milestone — read the relevant milestone before implementing |
| `TASKS.md` | The ordered task checklist — find your task here, check it off when done |
| `docs/THOTH_INGESTION_MAP.md` | Verified facts about `docs/book_of_thoth.pdf`'s structure (Tier 0), for the M6 ingestion parser |
| `docs/KNOWLEDGE_SOURCES.md` | Multi-source tier policy + structural notes for the Tier 1 companion sources (DuQuette, Ziegler) |
| `docs/adr/` | Architecture decision records for deviations from `DESIGN.md`'s provisional recommendations |
| `src/syzygy/domain/` | Pure Pydantic contracts. No Textual, no Kerykeion, no provider SDK imports — ever |
| `src/syzygy/astrology/` | `AstrologyEngine` protocol, Syzygy's orb policy, (later) the Kerykeion adapter and ranker |
| `src/syzygy/sortes/` | Deck loading, entropy collection, the unbiased draw |
| `src/syzygy/interpretation/` | `InterpretationProvider` protocol, the fixture provider, (later) context builder + real providers |
| `src/syzygy/storage/` | SQLite connection + migrations (append-only, never edit a merged migration) |
| `src/syzygy/resources/thoth_deck.yaml` | The canonical 78-card deck — single source of truth for card metadata |
| `src/syzygy/tui/` | The Textual app: `app.py` (shell + injected `SyzygyServices`), `screens/`, `widgets/`, `syzygy.tcss` |
| `src/syzygy/knowledge/` | Book of Thoth + companion-source ingestion (`normalize.py`, `segment.py`, `store.py`, `ingest.py`) and retrieval (`retrieve.py`) — Milestone 6 |
| `tests/` | Mirrors `src/syzygy/` layout |

## Workflow

1. Read the relevant section of `IMPLEMENTATION_PLAN.md` for your task
   before writing code. If your task isn't in `TASKS.md` yet, it's
   probably too large — ask, or break it down first.
2. Inspect the existing code in the module you're touching (and its
   tests) before editing — don't assume; read it.
3. Implement. Keep domain logic out of `syzygy.tui` and prompt-building
   out of `syzygy.interpretation.providers` — see the boundaries above.
4. Add or update tests for any deterministic behavior you change.
   Non-deterministic pieces (LLM prose, real astrology output) get tested
   through their surrounding contracts (schema validation, adapter
   normalization), not by asserting exact output.
5. Run the commands below. Do not leave the repository with a failing
   test or a lint error you introduced.
6. Check off the task in `TASKS.md` (`- [ ]` → `- [x]`) and leave a short
   note if you deviated from the plan or left something explicitly
   unfinished for the next task.
7. Commit and push to `main` automatically once the task is complete and
   the commands in the next section pass — do not wait for the user to
   ask. Use a normal commit (no `--no-verify`, no force-push); a regular
   `git push` to `main` is pre-authorized by this file for work done
   under this workflow. Still stop and ask before anything destructive
   (`--force`, `reset --hard`, rewriting published history) or before
   pushing something the verification commands don't pass cleanly.

## Commands (all verified to work in this repository)

Requires Python **3.11, 3.12, or 3.13** — not 3.14. Kerykeion 5.12.x
declares support for 3.10–3.13 only, and Textual has a known
`asyncio`-event-loop-policy regression on 3.14 (see
`pyproject.toml`'s comment above `requires-python`). If your system
Python is 3.14 (check with `python3 --version`), create a virtualenv
against an older interpreter first — e.g. via `mise install python@3.13`
or `pyenv`, then `python3.13 -m venv .venv`. Do not attempt to "fix"
Textual/Kerykeion to work on 3.14; wait for their upstream support instead.

```bash
# from a Python 3.11-3.13 interpreter
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                 # full test suite
ruff check .           # lint
mypy src               # type check
syzygy dev deck        # enumerate the canonical 78-card deck
syzygy doctor          # environment sanity check
syzygy tui             # launch the interface (bare `syzygy` does the same)
```

All four (`pytest`, `ruff check .`, `mypy src`, and both `syzygy`
subcommands) currently pass/succeed against a clean checkout — treat any
regression as something to fix before moving on, not a pre-existing issue.

## What's real vs. what's next

Implemented and tested: domain schemas, `AstrologyEngine` protocol +
Kerykeion adapter, transit orb policy + ranking, deck loader + data,
entropy collection, the unbiased draw, the reading state machine (types
and the storage-backed service/repositories that drive it), SQLite schema
+ migrations, the interpretation context builder and the versioned prompt
contract (`syzygy.interpretation.prompts`), both wired into
`reading_service`, all four `InterpretationProvider`s (`FixtureProvider`
plus the three real ones - `llama_cpp`, `openai`, `anthropic`, all
transport-only over `httpx` and sharing one parse/validate/repair-retry
path in `interpretation.providers.structured_output`), OS-keyring-backed
API key storage (`interpretation.providers.api_keys`), provider
*selection* (`interpretation.providers.selection`: a persisted provider +
model id in `AppPaths.settings_path`, never the readings database) now
wired into `syzygy.tui.app.default_services` - a reading actually uses
whatever `syzygy model use` last selected, falling back to
`FixtureProvider` (with a printed reason) if that provider can't be built,
so the ritual still never requires a model configured - the Book of Thoth
+ companion-source (DuQuette, Ziegler) ingestion pipeline and retrieval
(`syzygy.knowledge`), the TUI ritual (welcome → profile → home → Wheel →
reveal → reading, plus chart and a list-only archive), the CLI
(`dev deck`/`dev astrology`, `profile create`/`list`, `chart`,
`knowledge ingest`/`status`, `model status`/`configure`/`use`, `tui`,
`doctor`; bare `syzygy` launches the TUI).

Not yet implemented (see `TASKS.md` for the ordered list, and don't
assume a stub exists just because a directory is mentioned in
`IMPLEMENTATION_PLAN.md`): the full archive with statistics, the glyph
capability detection and "terminal too small" state.
