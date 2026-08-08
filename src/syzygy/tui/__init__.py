"""The Syzygy terminal interface (Textual).

Nothing in this package owns astrology, randomness, prompt construction,
or persistence rules - it calls `syzygy.storage.reading_service`,
`syzygy.sortes`, and `syzygy.astrology` and renders what they return
(AGENTS.md: "TUI code does not own astrology logic"). Textual types stay
inside this package; no screen or widget is imported by the domain,
storage, or interpretation layers.
"""

from __future__ import annotations

__all__ = ["SyzygyApp", "run"]


def __getattr__(name: str) -> object:
    # Imported lazily so that `import syzygy.tui` (e.g. from the CLI's
    # argument parser) does not pull Textual in until the app actually runs.
    if name in __all__:
        from syzygy.tui.app import SyzygyApp, run

        return {"SyzygyApp": SyzygyApp, "run": run}[name]
    raise AttributeError(name)
