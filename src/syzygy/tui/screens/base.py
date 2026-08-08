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


class SyzygyScreen(Screen[None]):
    """A screen with typed access back to the Syzygy application."""

    @property
    def syzygy(self) -> SyzygyApp:
        # `App` is generic over its return type only, so the concrete app
        # type has to be asserted here rather than parameterized.
        return cast("SyzygyApp", self.app)


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
