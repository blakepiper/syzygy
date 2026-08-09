<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="logo-light.svg">
  <img alt="Syzygy" src="logo-light.svg" width="100%">
</picture>

A local-first terminal application for a daily divination ritual combining:

- **Self** — your saved natal chart
- **Cosmos** — deterministic current astrological transits against that chart
- **Chance** — one truly random upright card from the 78-card Crowley-Harris Thoth Tarot
- **Interpretation** — an LLM synthesizing those fixed inputs, grounded in Aleister Crowley's *The Book of Thoth*

The LLM interprets; it never calculates astrology, selects the card, or rerolls it.

## Status

Pre-release, under active development, but the full daily ritual works
end to end: create a profile, turn the Wheel, draw a card, and read an
interpretation. Interpretation can come from a locally hosted
[`llama.cpp`](https://github.com/ggml-org/llama.cpp) server, OpenAI, or
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

One optional extra adds hosted-provider support:

```bash
pip install ".[providers]"      # OpenAI / Anthropic hosted providers
                                 # (httpx, keyring - not needed for the
                                 # local llama.cpp provider, which has no
                                 # extra dependency)
```

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

First launch creates a profile from birth data (date, time, place,
coordinates, timezone — or resolved automatically from a place name if
the lookup service is reachable), calculates its natal chart, and drops
you on the daily home screen. From there, `[Enter]` turns the Wheel for
today's reading; `[C]` opens the natal chart, `[A]` the archive.

By default, readings use the built-in fixture provider — deterministic
placeholder prose, useful for trying the ritual with no setup. To use a
real model instead:

```bash
# A local model via llama.cpp's server (http://127.0.0.1:8080 by default,
# localhost-only) - no API key, no extra dependency:
syzygy model use llama_cpp --model <model-name>

# A hosted provider - requires the `providers` extra and an API key
# (stored in the OS keyring, never in the readings database):
syzygy model configure openai      # prompts for the key (hidden input)
syzygy model use openai --model gpt-4o-mini
syzygy model status                # see what's configured and what's active
```

Selecting a hosted provider sends that day's reading context (profile
name, chart placements, the drawn card, ranked transits, and any matched
source passages) to its servers on every reading — `model use` prints
this disclosure before saving the selection.

To ground interpretations in the actual Book of Thoth text rather than
just the deck's structured correspondences, ingest a PDF you already have
a personal copy of (none is bundled — `docs/*.pdf` is gitignored):

```bash
syzygy knowledge ingest /path/to/book_of_thoth.pdf
syzygy knowledge status
```

## Documentation

- [`DESIGN.md`](DESIGN.md) — product design and rationale
- [`AGENTS.md`](AGENTS.md) — operating manual for coding agents working in this repository
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — implementation-specific architecture, milestone by milestone
- [`TASKS.md`](TASKS.md) — the ordered task checklist
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
