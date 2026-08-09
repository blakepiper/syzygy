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


#: The layout tiers (M12.5d). Three of them, defined here and nowhere
#: else - `syzygy.tcss` styles the `-compact`/`-wide` classes this module
#: sets, and M14's animations and the too-small gate use the same numbers
#: rather than picking their own.
#:
#:   below 80x24          the floor. `syzygy.tui.screens.too_small` takes
#:                        over; no layout is expected to work down there.
#:   80x24 - 99x31        `-compact`. Same content, same shape, trimmed
#:                        padding. Nothing may be hidden that carries
#:                        information (docs/old/DESIGN.md section 18.6).
#:   100x32 - 119 wide    the regular tier, no class. One column.
#:   120 wide and up      `-wide`. Screens go multi-column: the space
#:                        exists, so it gets used rather than padded
#:                        around (M12.5).
#:
#: docs/old/DESIGN.md section 18.6's ideal terminal size. At or above this, a
#: screen renders at full size; below it (but still at or above the
#: compact floor in `syzygy.tui.screens.too_small`), screens get a
#: `-compact` class to trim padding/decoration rather than truncating.
IDEAL_WIDTH = 100
IDEAL_HEIGHT = 32

#: Width at which a screen has room for parallel columns. Chosen from the
#: narrowest thing that has to fit beside another: `HomeScreen`'s SELF
#: column is an anchor line like "☉ Sun    ♍ Virgo      14°22'" at ~36
#: cells, and three of those plus padding need 120. Below it the same
#: content stacks - the wide layouts are a second arrangement of the same
#: widgets, never a second set of them.
WIDE_WIDTH = 120

#: Height at which a screen has rows to spare, as `-tall`. Separate from
#: `-wide` because the two are independent: a 200x30 terminal is wide and
#: not tall, and a 90x60 one is the reverse. Only objects whose size is
#: bounded by rows rather than columns should use it - today that is the
#: reveal's card, which is the whole point of that screen and was sitting
#: at a third of the height of a full-screen terminal.
TALL_HEIGHT = 48


class SyzygyScreen(Screen[None]):
    """A screen with typed access back to the Syzygy application.

    Also owns layout-tier detection (docs/old/DESIGN.md section 18.6, M12.5d) in
    one place, via `on_screen_resume`/`on_resize`, rather than each screen
    measuring itself. A subclass that overrides `on_screen_resume` must
    call `super().on_screen_resume()` to keep this working.
    """

    @property
    def syzygy(self) -> SyzygyApp:
        # `App` is generic over its return type only, so the concrete app
        # type has to be asserted here rather than parameterized.
        return cast("SyzygyApp", self.app)

    def on_screen_resume(self) -> None:
        self._update_size_classes()

    def on_resize(self) -> None:
        self._update_size_classes()

    def _update_size_classes(self) -> None:
        compact = self.size.width < IDEAL_WIDTH or self.size.height < IDEAL_HEIGHT
        self.set_class(compact, "-compact")
        # Width only. A wide layout trades height for width - three
        # columns need *fewer* rows than the same content stacked - so a
        # short terminal is a reason to go multi-column, not to avoid it.
        self.set_class(self.size.width >= WIDE_WIDTH, "-wide")
        self.set_class(self.size.height >= TALL_HEIGHT, "-tall")


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
