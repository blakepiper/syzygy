"""Guided local-model setup (M16).

Everything needed to take a person who has never run a local LLM from
"I'd like readings interpreted privately" to a working, verified
`llama_cpp` provider: machine inventory, a curated model catalog, runtime
and model acquisition, a supervised localhost server, and a Syzygy-shaped
smoke test that must pass before the provider is ever activated.

**This package contains no Textual and no provider SDK.** The TUI wizard
(`syzygy.tui.screens.local_setup`) and the CLI (`syzygy model
setup-local`) are two front ends over `orchestrator.LocalSetupSession`;
neither owns platform, process, or network code. HTTP that speaks to a
model stays in `syzygy.interpretation.providers` - this package consumes
the typed result of a probe rather than re-implementing it.

The invariants in `AGENTS.md` are unchanged by any of it. A local model
still receives only an `InterpretationContext`, still never selects a
card, and still never calculates astrology. Setup and verification cannot
create a reading or touch the readings database at all.
"""

from __future__ import annotations
