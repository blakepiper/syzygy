# Syzygy

A local-first terminal application for a daily divination ritual combining:

- **Self** — your saved natal chart
- **Cosmos** — deterministic current astrological transits against that chart
- **Chance** — one truly random upright card from the 78-card Crowley-Harris Thoth Tarot
- **Interpretation** — an LLM synthesizing those fixed inputs, grounded in Aleister Crowley's *The Book of Thoth*

The LLM interprets; it never calculates astrology, selects the card, or rerolls it.

## Status

Pre-release, under active development. Not yet installable as a finished product.

## Documentation

- [`DESIGN.md`](DESIGN.md) — product design and rationale
- [`AGENTS.md`](AGENTS.md) — operating manual for coding agents working in this repository
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — implementation-specific architecture, milestone by milestone
- [`TASKS.md`](TASKS.md) — the ordered task checklist
- [`docs/THOTH_INGESTION_MAP.md`](docs/THOTH_INGESTION_MAP.md) — structure of the bundled Book of Thoth PDF

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
syzygy dev deck
syzygy doctor
```

Requires Python >=3.11,<3.14 (see `AGENTS.md` for why the upper bound exists).

## License

AGPL-3.0-or-later (see [`LICENSE`](LICENSE)). This follows from the license
of the Kerykeion astrology library this project depends on — see
[`docs/adr/0001-agpl-license-for-kerykeion.md`](docs/adr/0001-agpl-license-for-kerykeion.md).

The bundled `docs/book_of_thoth.pdf` is Aleister Crowley's *The Book of
Thoth*, included as a personal reference copy for local knowledge-base
ingestion. It is not covered by this project's license and is not
redistributed as part of the installable package.
