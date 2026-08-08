"""Shared screen scaffolding.

Screens reach the application's collaborators (database connection, clock,
astrology engine, interpretation provider) through `SyzygyScreen.syzygy`
rather than importing or constructing any of them - the app owns the wiring
so tests can substitute a fixture engine and provider wholesale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.screen import Screen
from textual.widgets import Static

if TYPE_CHECKING:
    from syzygy.tui.app import SyzygyApp


#: DESIGN.md section 18.6's ideal terminal size. At or above this, a
#: screen renders at full size; below it (but still at or above the
#: compact floor in `syzygy.tui.screens.too_small`), screens get a
#: `-compact` class to trim padding/decoration rather than truncating.
IDEAL_WIDTH = 100
IDEAL_HEIGHT = 32


class SyzygyScreen(Screen[None]):
    """A screen with typed access back to the Syzygy application.

    Also owns compact-mode detection (DESIGN.md section 18.6) in one
    place, via `on_screen_resume`/`on_resize`, rather than each screen
    checking its own size. A subclass that overrides `on_screen_resume`
    must call `super().on_screen_resume()` to keep this working.
    """

    @property
    def syzygy(self) -> SyzygyApp:
        # `App` is generic over its return type only, so the concrete app
        # type has to be asserted here rather than parameterized.
        return cast("SyzygyApp", self.app)

    def on_screen_resume(self) -> None:
        self._update_compact_class()

    def on_resize(self) -> None:
        self._update_compact_class()

    def _update_compact_class(self) -> None:
        compact = self.size.width < IDEAL_WIDTH or self.size.height < IDEAL_HEIGHT
        self.set_class(compact, "-compact")


class TitleBar(Static):
    """`SYZYGY` on the left, context (usually the date) on the right."""

    def __init__(self, right_text: str = "", *, id: str | None = None) -> None:
        super().__init__(id=id, classes="title-bar")
        self.right_text = right_text

    def on_mount(self) -> None:
        self.render_title()

    def set_right_text(self, right_text: str) -> None:
        self.right_text = right_text
        self.render_title()

    def render_title(self) -> None:
        width = max(self.size.width, 30)
        left = "SYZYGY"
        padding = max(1, width - len(left) - len(self.right_text))
        self.update(f"{left}{' ' * padding}{self.right_text}")

    def on_resize(self) -> None:
        self.render_title()
