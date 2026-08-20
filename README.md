<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="logo-light.svg">
  <img alt="Syzygy" src="logo-light.svg" width="100%">
</picture>

A local-first terminal application for a daily divination ritual combining:

- **Self** — your saved natal chart
- **Cosmos** — deterministic current astrological transits against that chart
- **Chance** — one truly random upright Thoth card (and, in the Oracle, a six-line I Ching cast alongside it)
- **Interpretation** — an LLM synthesizing those fixed inputs, grounded in Aleister Crowley's *The Book of Thoth*

The LLM interprets; it never calculates astrology, selects a card or hexagram, or rerolls it.

## Status

Pre-release, under active development, but the full daily ritual works
end to end: create a profile, turn the Wheel, draw a card, and read an
interpretation. The question-led Oracle works alongside it: ask in your
own words, turn the Wheel once, and receive a direct response — read from a
fixed Thoth card standing in a fixed I Ching hexagram — in the same esoteric
and conventional registers. Interpretation
can come from a model Syzygy sets up and
runs on your own computer (guided, no terminal required — see
[`docs/LOCAL_MODELS.md`](docs/LOCAL_MODELS.md)), a
[`llama.cpp`](https://github.com/ggml-org/llama.cpp) server you run
yourself, OpenAI, or
Anthropic; with none of those configured, it falls back to a built-in
fixture provider so the ritual is never blocked on having a model set up.

## Installation

Requires Python **3.11, 3.12, or 3.13** — not 3.14 (Kerykeion and Textual
don't yet support 3.14; see `AGENTS.md` for details). Check your version
with `python3 --version`; if it's 3.14, install an older interpreter
first, e.g. via [`mise`](https://mise.jdx.dev/) (`mise install
python@3.13`) or `pyenv`.

```bash
git clone <this repository> syzygy
cd syzygy
python3.13 -m venv .venv        # or python3.11 / python3.12
source .venv/bin/activate
pip install .                   # complete local app: TUI, CLI, astrology,
                                 # birthplace lookup, theme music, and the
                                 # fixture interpretation provider
```

Hosted OpenAI and Anthropic providers are included in the standard install.
Their API keys are stored via the system keyring; configure one from the model
setup screen or with `syzygy model configure`.

Birthplace geocoding and looping theme playback are included in the main
install. If a geocoding request fails, coordinates and timezone can still
be entered manually. If no audio device is available, the app starts
silently. `syzygy --no-audio` explicitly starts a session without music,
and `[S]` mutes and unmutes at any point (the choice is remembered).

Then run `syzygy doctor` to confirm the install is healthy, and `syzygy`
to launch the interface:

```bash
syzygy doctor    # deck validation, data directory, knowledge base and
                 # provider status - safe to run any time
syzygy           # launch the TUI (same as `syzygy tui`); first run walks
                 # you through creating a profile
```

### NixOS / Nix shortcut

On a machine with `nix-shell`, `./nix-start` creates a private Python 3.13
virtualenv at `.nix-venv-py313`, installs this checkout into it, and launches
Syzygy. It accepts the normal CLI arguments, so `./nix-start doctor` checks
the environment and bare `./nix-start` opens the TUI. This is optional; the
standard virtualenv setup above remains the supported path on non-Nix systems.
It does not add `syzygy` to your outer shell's `PATH`; use `./nix-start` each
time, or follow the standard virtualenv setup if you want the `syzygy` command
available after activation.

First launch creates a profile from birth data (date, time, place,
coordinates, timezone — or resolved automatically from a place name if
the lookup service is reachable), calculates its natal chart, and drops
you on the daily home screen. From there, `[Enter]` turns the Wheel for
today’s reading; `[C]` opens the natal chart, `[A]` the archive.

### The Oracle

Press `[O]` from home, ask a question, and turn the Wheel once. There is no
mode to choose: one turn casts **both** oracles, and Syzygy fixes what each
one is for.

- The **hexagram** is the ground — the character of the time you are asking in.
- The **card** is the figure — the specific thing the oracle puts in front of
  you, standing in that ground.
- **Changing lines** and the resulting hexagram are where the ground is
  unstable, and which way it is going. Roughly one consultation in six has no
  changing line at all; that is a settled time, not a missing answer.
- The **Image** is conduct — how to bear yourself in it.

Syzygy chooses nothing here. It assigns the roles and hands both fixed objects
to the interpreter; the model is never asked which one governs, and there is no
correspondence table between the 64 hexagrams and the 78 cards — none is used,
and none may be invented. The reasoning is recorded in
[ADR 0008](docs/adr/0008-oracle-as-figure-and-ground.md).

**The Oracle does not use the day's transits.** A question is usually about a
horizon a transit is not on, and a Moon aspect exact for four hours has no
business shaping an answer about a decision six months out. Your natal chart
still reaches the interpretation — the card can speak to it, since both use
planets, signs, decans, and elements. The daily reading is unchanged and keeps
its transits, because a daily reading *is* about today.

The Oracle is separate from the canonical daily reading: it neither consumes
nor changes today's card, and it is available whether or not the daily rite is
complete. Consultations are unlimited, but each is its own act — one question,
one turn of the Wheel, one card and one cast. Both are committed to storage
before any model is called, so retrying a failed interpretation always reuses
them; asking again creates a visibly new consultation rather than a reroll or
a second opinion on the old one.

The I Ching uses the three-coin method, casting six lines from bottom to top.
The exact probabilities and the method are recorded in
[ADR 0007](docs/adr/0007-i-ching-as-an-alternative-oracle.md). All 64
judgments, Images, and line texts come from James Legge's 1882 translation,
with page citations stored on every canonical entry.

The original question is stored locally with the consultation in Syzygy's
SQLite database. It is sent only to the configured interpretation provider;
with a managed local model or the fixture provider it never leaves the
machine. It is treated as quoted data in the prompt and cannot replace the
card, the cast, astrology facts, or the structured output contract.

Consultations made before this design — a card alone, or a cast alone — stay
in the archive and stay readable. They are labelled as the earlier rite they
were, and they cannot be re-run.

The same rite is available from the command line:

```bash
syzygy oracle ask "What am I not seeing clearly?"
syzygy oracle list
syzygy oracle show <consultation-id>
```

By default, readings use the built-in fixture provider — deterministic
placeholder prose, useful for trying the ritual with no setup. That text
is canned: it is the same whatever your chart, transits, and card are, and
the interface always says which of the two you are looking at.

### A model on your own computer

Press `[M]` in the interface and choose **Set up a local model for me**.
Syzygy inventories the machine, recommends a model that will actually run
on it, shows an itemised list of everything it proposes to download and
where it will go, and only then asks. Nothing is downloaded, installed,
started, or switched over without an explicit confirmation.

Once it is set up, prompts never leave the machine: the model runs as a
process bound to `127.0.0.1`, which Syzygy starts when a reading needs it
and stops when you quit.

The same flow from a terminal:

```bash
syzygy model setup-local          # interactive; prints a plan and asks first
syzygy model local status         # what is configured, and where
syzygy model local doctor         # is it healthy?
```

Full walkthrough, storage layout, privacy boundary, supported hardware,
licences, and troubleshooting: [`docs/LOCAL_MODELS.md`](docs/LOCAL_MODELS.md).

### An existing server, or a hosted provider

```bash
# A llama.cpp/LM Studio/Ollama server you run yourself:
syzygy model use llama_cpp --base-url http://127.0.0.1:8080/v1 --model <name>

# A hosted provider - requires an API key, stored in the OS keyring and
# never in the readings database:
syzygy model configure openai      # prompts for the key (hidden input)
syzygy model use openai --model gpt-4o-mini
syzygy model status                # see what's configured and what's active
```

Selecting a hosted provider sends the interpretation context (profile name,
chart placements, the drawn card, ranked transits, any matched source
passages, and an Oracle question when making a consultation) to its servers —
`model use` prints this disclosure before saving the selection.

### Source material

Every install ships an index of **where** each of the 78 cards is
discussed in three books — source, heading, page range — and **none of
what those pages say**. The books are still under copyright; the index is
Syzygy's own derived work, so it travels and the prose does not (see
[`docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`](docs/adr/0003-ship-derived-knowledge-index-without-source-text.md)).

So on a fresh install, a reading shows you where to go and read for
yourself, and the model is given no passages. Press `[I]` on any reading
to see both lists. **That is still a real reading**: the card, its
correspondences, and the ranked transits are all grounded in
`thoth_deck.yaml`, which is itself sourced from *The Book of Thoth* and
cited page by page. What is missing is Crowley's prose, not the
attributions.

Save your copies under these exact names:

- `docs/book_of_thoth.pdf`
- `docs/mirror_of_the_soul.pdf`
- `docs/understanding_crowley_thoth_tarot.pdf`

Then ingest all three at once; their passages become part of readings from
then on:

```bash
syzygy knowledge ingest
syzygy knowledge status
```

The `[K]` screen and `syzygy knowledge ingest /path/to/one.pdf` remain
available when you want to install or replace one source at a time.

Nothing is ever downloaded. `[K]` accepts only a file whose hash matches
the edition the shipped citations were built against, because every page
range in the app is that edition's pagination; the CLI will ingest
another copy if you know yours differs and accept what that means.

## Documentation

- [`docs/old/DESIGN.md`](docs/old/DESIGN.md) — product design and rationale
- [`AGENTS.md`](AGENTS.md) — operating manual for coding agents working in this repository
- [`docs/old/IMPLEMENTATION_PLAN.md`](docs/old/IMPLEMENTATION_PLAN.md) — implementation-specific architecture, milestone by milestone
- [`TASKS.md`](TASKS.md) — the ordered task checklist
- [`docs/LOCAL_MODELS.md`](docs/LOCAL_MODELS.md) — running a model on your own computer: what is downloaded, the privacy boundary, hardware, troubleshooting
- [`docs/LOCAL_MODEL_MAINTENANCE.md`](docs/LOCAL_MODEL_MAINTENANCE.md) — maintainers: refreshing the pinned runtime and model catalogue, running evaluations
- [`docs/THOTH_INGESTION_MAP.md`](docs/THOTH_INGESTION_MAP.md) — structure of the bundled Book of Thoth PDF
- [`docs/KNOWLEDGE_SOURCES.md`](docs/KNOWLEDGE_SOURCES.md) — the knowledge-base source tiers and where to get the source PDFs

## Development

```bash
pip install -e ".[dev,providers,geocoding,audio]"
pytest
ruff check .
mypy src

syzygy            # launch the terminal interface (same as `syzygy tui`)
syzygy dev deck
syzygy doctor
```

## License

AGPL-3.0-or-later (see [`LICENSE`](LICENSE)). This follows from the license
of the Kerykeion astrology library this project depends on — see
[`docs/adr/0001-agpl-license-for-kerykeion.md`](docs/adr/0001-agpl-license-for-kerykeion.md).

The bundled `docs/book_of_thoth.pdf` is Aleister Crowley's *The Book of
Thoth*, included as a personal reference copy for local knowledge-base
ingestion. It is not covered by this project's license and is not
redistributed as part of the installable package.
