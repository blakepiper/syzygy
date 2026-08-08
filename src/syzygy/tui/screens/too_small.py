"""The "terminal too small" state (DESIGN.md section 18.6, `TASKS.md`
M9.3): below the compact floor of 80x24, do not let a screen render
broken or truncated - show a clean, static message instead.

`SyzygyApp` pushes this screen on top of whatever was active when the
terminal shrinks below the floor, and pops it once the terminal grows
back - the screen underneath is never torn down, so mid-ritual state
(e.g. an in-progress Wheel draw) survives the round trip.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.widgets import Static

from syzygy.tui.screens.base import SyzygyScreen

#: DESIGN.md section 18.6's suggested compact floor - below this, layouts
#: are not guaranteed to render usably.
MIN_WIDTH = 80
MIN_HEIGHT = 24


class TooSmallScreen(SyzygyScreen):
    """A static, centered notice. There is nothing safe to do here besides
    quit, which the app-level binding (`SyzygyApp.BINDINGS`) already
    provides.
    """

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Static("", id="too-small-message", classes="muted")

    def on_mount(self) -> None:
        self.update_size(self.app.size.width, self.app.size.height)

    def update_size(self, width: int, height: int) -> None:
        self.query_one("#too-small-message", Static).update(
            "SYZYGY needs a larger terminal.\n\n"
            f"Current size: {width}x{height}\n"
            f"Minimum size: {MIN_WIDTH}x{MIN_HEIGHT}\n\n"
            "Resize the terminal to continue."
        )
