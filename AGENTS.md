# AGENTS.md — Syzygy operating manual

Compact, durable rules for any coding agent working in this repository.
This is not the design doc — read `docs/old/DESIGN.md` for product intent and
rationale, and `TASKS.md` for how the milestone you are working on should
be built (`docs/old/IMPLEMENTATION_PLAN.md` holds the same for M0–M9, which are
done). This file is what you should already have loaded before touching
code.

## The one-paragraph mental model

```
SELF (saved natal chart) + COSMOS (current transits) + CHANCE (one random
Thoth card, or one I Ching cast in that Oracle mode) → SYZYGY → an LLM
interprets the fixed result in two
registers (Esoteric, Conventional). The LLM never calculates astrology,
never selects or changes the card, and can never cause a reroll.
```

If a task you're given seems to require the model to decide a fact instead
of receiving one, stop and re-read `docs/old/DESIGN.md` section 5.2 — that's almost
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
  (`docs/old/DESIGN.md` section 31).
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
  implemented — see `docs/old/IMPLEMENTATION_PLAN.md` Milestone 2). The LLM
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
- **Canonical I Ching data comes from
  `src/syzygy/resources/iching_legge.yaml`, never model memory.** Its 64
  judgments, Images, and line texts are transcribed and page-cited from James
  Legge's 1882 translation. The three-coin method, changing-line treatment,
  and alternative-mode decision are fixed by ADR 0007; a provider receives
  the committed cast and source text and may not select or alter either.
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
- **A local model is acquired, never bundled, and never trusted on
  faith.** Everything `syzygy.local_models` downloads is pinned in
  `src/syzygy/resources/local_models/` by immutable revision *and*
  sha256, over HTTPS, from an allowlisted host; the digest is verified
  before anything is extracted, executed, or promoted. Nothing tracks
  "latest". A managed server binds `127.0.0.1` only, carries no reading
  content on its command line, and is started on demand and stopped on
  exit. Nothing in the package invokes a shell, requests elevation, or
  compiles from source. Cleanup may delete only what an `OWNERSHIP.json`
  marker proves Syzygy created - never an external binary, a
  user-supplied model file, or another application's cache. The provider
  is not activated until the smoke test in `local_models.verification`
  passes, and that smoke test may not create a reading, draw a card, or
  touch the readings database. See
  `docs/adr/0005-guided-local-model-setup.md`.
- **No LangChain, LlamaIndex, hosted vector DB, agent framework, dependency
  injection container, or web framework.** If you think you need one,
  you're probably over-engineering a small local app — re-read
  `docs/old/ARCHITECTURE_HANDOFF.md` section 11 first.
- **Every dependency must be AGPL-3.0 compatible** (permissive licenses are
  always fine; other copyleft licenses need review) — see
  `docs/adr/0001-agpl-license-for-kerykeion.md`.

## Keep licensing in proportion

Syzygy is a non-monetized personal art project built on divinatory traditions
that are centuries or millennia old and have no owner. The tarot, the I Ching,
astrology, the Qabalah, hexagram and trigram structure, decan attributions,
planetary and zodiacal correspondences — none of this is anyone's property, and
free, usable sources for all of it exist. Treat that as the default, and go
find one.

There are exactly two real licensing constraints in this repository, both
already decided:

1. **The three modern books** (`docs/*.pdf` — Crowley, DuQuette, Ziegler) are
   under copyright. That is why the shipped index carries citations and vectors
   but never passages (ADR 0003). This is settled; apply it, don't re-derive it.
2. **Dependencies must be AGPL-3.0 compatible** (the bullet above).

Everything else is ordinary work. So:

- Do not open a task, milestone, or ADR with a licensing review, and do not
  make one a blocker or a gate on work that is otherwise ready. If a specific
  modern *translation or edition* is in copyright, that is a two-line note and
  a pointer to a free alternative — not a milestone precondition, and not a
  reason to consider shipping structural data with no commentary as an
  "acceptable outcome."
- Do not extend rule 1 by analogy. The three books are a specific, narrow
  exception with a written rationale. They are not a template to apply to every
  text Syzygy might ever read.
- State a legal caveat once, plainly, where it changes what gets built. Don't
  restate it in the summary, the commit message, and the definition of done.
- When the answer is "a free source almost certainly exists," the task is to
  find and cite one, not to write a plan for evaluating whether one may be
  sought.

Grounding discipline is a *separate* concern and is not relaxed here: canonical
data still comes from a real source and a real citation, never from model
memory (see the `thoth_deck.yaml` invariant above). "Public domain" means you
may use it freely — it does not mean you may invent it.

## Repository map

| Path | What lives here |
|---|---|
| `docs/old/DESIGN.md` | Product design and rationale — read when product intent is unclear |
| `TASKS.md` | The ordered task checklist: a one-line history of every shipped milestone, then the full spec for current work (M21 onward) — find your task here, check it off when done |
| `docs/old/IMPLEMENTATION_PLAN.md` | Concrete architecture per milestone for M0–M9. History; current work is in `TASKS.md` |
| `docs/animation.md` | The animation design spec M14 is written against — read before touching motion |
| `docs/BRAND_ASSETS.md` | How the bundled logo/mascot PNGs and the theme MP3 are produced and where they live |
| `docs/THOTH_INGESTION_MAP.md` | Verified facts about `docs/book_of_thoth.pdf`'s structure (Tier 0), for the M6 ingestion parser |
| `docs/KNOWLEDGE_SOURCES.md` | Multi-source tier policy + what may and may not be committed from the books |
| `docs/LOCAL_MODELS.md` | The user-facing guide to running a model locally: what is downloaded, the privacy boundary, hardware, troubleshooting |
| `docs/LOCAL_MODEL_MAINTENANCE.md` | Maintainers: refreshing the pinned llama.cpp release and model catalog, running the evaluation harness, adding a platform |
| `docs/adr/` | Architecture decision records for deviations from `docs/old/DESIGN.md`'s provisional recommendations |
| `src/syzygy/domain/` | Pure Pydantic contracts. No Textual, no Kerykeion, no provider SDK imports — ever |
| `src/syzygy/astrology/` | `AstrologyEngine` protocol, Syzygy's orb policy, the Kerykeion adapter and ranker |
| `src/syzygy/sortes/` | Deck loading, entropy collection, the unbiased draw |
| `src/syzygy/interpretation/` | `InterpretationProvider` protocol, the prompt contract, context builder, and the four providers |
| `src/syzygy/local_models/` | Guided local-model setup (M16): inventory, fit, pinned catalog, discovery, download, supervisor, smoke test, orchestrator. No Textual, no provider SDK |
| `src/syzygy/storage/` | SQLite connection + migrations (append-only, never edit a merged migration) |
| `src/syzygy/knowledge/` | Ingestion (`normalize`/`segment`/`store`/`ingest`), retrieval (`retrieve`), per-source state (`status`), and the shipped citations+vectors index (`artifact`, `embedding`) |
| `src/syzygy/settings.py` | The namespaced settings document. Add a preference as a *section*; never write the whole file |
| `src/syzygy/audio.py` | The bundled looping theme. Degrades to `SilentTheme` on every failure |
| `src/syzygy/dev.py` | Development-only affordances, all gated on `SYZYGY_DEV` |
| `src/syzygy/resources/` | `thoth_deck.yaml` (canonical card metadata), `art/` (78 card PNGs), `brand/`, `audio/`, `knowledge/` (citations + vectors), `local_models/` (pinned model catalog + llama.cpp manifest) |
| `src/syzygy/tui/` | The Textual app: `app.py` (shell + injected `SyzygyServices`), `screens/`, `widgets/`, `palette.py`, `syzygy.tcss` |
| `tests/` | Mirrors `src/syzygy/` layout |

## Workflow

1. Read your task's entry in `TASKS.md` before writing code (for M0–M9
   work, `docs/old/IMPLEMENTATION_PLAN.md` instead). If your task isn't in
   `TASKS.md` yet, it's probably too large — ask, or break it down first.
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

Added since (M10–M15, `TASKS.md`): birthplace geocoding on profile
creation, in-TUI model setup including a local-server form with a live
probe (`tui/screens/model_setup.py`), profile deletion in both interfaces,
bundled card art and brand assets rendered as terminal half-blocks
(`tui/widgets/pixel_art.py`, `card_art.py`, `brand.py`), the palette in one
place (`tui/palette.py`, kept in step with `syzygy.tcss` by a test), a
dev-only reroll gated on `SYZYGY_DEV` (`syzygy.dev`), the shipped
knowledge index of citations and vectors (`knowledge/artifact.py`,
`knowledge/embedding.py`, ADR 0003), the namespaced settings document
(`syzygy.settings` — add a preference as a *section*, never by writing the
whole file), the looping theme bundled in the main install
(`syzygy.audio`, which degrades to `SilentTheme` on every failure), and
the layout tiers (M12.5), and today's cosmos — the full ranked sky
against the natal chart, at `tui/screens/cosmos.py`, reached with `[T]`
from home (M13.1), on-demand cached LLM summaries for the natal chart and
daily cosmos (M13.2), and the elapsed-time animation layer under
`tui/animation/` with semantic events and persisted full/reduced/off
motion levels (M14).

**Local models (M16).** `syzygy.local_models` is the non-UI subsystem;
`tui/screens/local_setup.py` and `syzygy model setup-local` are two front
ends over one `orchestrator.LocalSetupSession`. Every OS touchpoint goes
through an injectable `local_models.probe.Probe`, so no test learns
anything about the machine running it, and no normal test downloads,
installs, spawns a process, probes real hardware, or opens a socket. The
shipped catalog entries are `provisional`: pinned, licence-reviewed, and
exact about memory, but the evaluation harness
(`local_models.evaluation`, `syzygy dev evaluate-local`) has not been run
against them, and the UI says so rather than implying evidence that does
not exist.

**Layout tiers.** `syzygy.tui.screens.base` owns the three thresholds and
sets `-compact`/`-wide`/`-tall` on every screen; `syzygy.tcss` styles
those classes. Do not measure `self.size` in a screen to decide a layout,
and do not introduce a fourth threshold without changing it there — the
too-small gate, the layout blocks, and M14's animations all read the same
numbers. `tests/tui/test_layout.py` checks each screen at the tier sizes,
in both directions: nothing that matters is off-screen, and what should
grow did.

Added in M16: guided local-model setup end to end - machine inventory and
a conservative fit estimate, a pinned publisher-owned model catalog and
llama.cpp runtime manifest, discovery and qualification of an existing
server or binary, resumable digest-verified downloads with safe archive
extraction, a localhost-only subprocess supervisor with typed startup
diagnosis and crash-safe process identity, a no-side-effect Syzygy smoke
test that gates activation, a resumable TUI wizard, and
`syzygy model setup-local` / `model local status|doctor|list|start|stop|remove`.

Added in M17: the opening sequence on every launch, default entry/exit
transitions on every screen, the mascot past first launch, an
unmistakable list highlight, arrow-key navigation through every menu, and
centred card art.

Added in M18: retrieval's citations persisted on the `Reading` (migration
6) separately from `InterpretationContext`, the `[I]` view's two lists
("passages sent" and "where this card is discussed"), the `[K]`
source-material screen, a one-line home note, and `doctor` telling
"citations only (normal)" apart from "broken". The rule this rests on is
in the invariants above and did not move: citation-only chunks reach the
user, never a provider.

Added in M19–M20: the question-led Oracle as a rite separate from the daily
reading, with mutually exclusive Thoth-card and I Ching modes. I Ching uses a
committed three-coin cast with changing lines and a resulting hexagram,
source-grounded Legge (1882) text, its own `iching-v1` prompt and storage state
machine, and the same retry-without-reroll provider boundary.

M21 wrote `docs/liber_syzygy.md`, the composed founding text. It is
gitignored on purpose and stays that way until the author says otherwise: do
not commit it, quote it into the README, render it in the TUI, or feed it to a
model as tone guidance. Placing it anywhere in the application is a separate,
unopened task.

All tasks through M21 are implemented, except M16.10f - the manual
clean-machine matrix, of which only Linux x86-64 CPU has actually been
performed (recorded in `docs/LOCAL_MODEL_MAINTENANCE.md`). M12.3 (a
Cinzel display treatment) was dropped rather than deferred - `TASKS.md`
records why.

**Where the current work is written down.** `docs/old/IMPLEMENTATION_PLAN.md`
covers M0–M9 and is history now; everything after that lives in `TASKS.md` -
shipped milestones as one summary row each, current work (M21 onward) as a
full spec. Read the milestone there before implementing.
