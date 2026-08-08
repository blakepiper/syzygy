"""First launch, with no self configured (DESIGN.md section 6.1)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.widgets import Footer, Static

from syzygy.tui.screens.base import SyzygyScreen

BANNER = r"""
 ███████ ██    ██ ███████ ██    ██  ██████  ██    ██
 ██       ██  ██     ███   ██  ██  ██        ██  ██
 ███████    ██      ███     ████   ██  ███     ██
      ██    ██     ███       ██    ██   ██     ██
 ███████    ██    ███████    ██     ██████     ██
"""


class WelcomeScreen(SyzygyScreen):
    """`SELF` is the first point of the alignment; nothing else can
    resolve until a profile exists."""

    BINDINGS = [
        ("n", "create_profile", "create profile"),
        ("q", "quit", "quit"),
    ]

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Static(BANNER, id="welcome-banner")
            with Center():
                with Vertical(id="welcome-body"):
                    yield Static("No self is configured.", classes="lede")
                    yield Static(
                        "A reading needs a natal chart. Nothing is calculated,\n"
                        "drawn, or interpreted before one exists.",
                        classes="muted",
                    )
                    yield Static("[N] Create profile     [Q] Quit", classes="keys", markup=False)
        yield Footer()

    def action_create_profile(self) -> None:
        self.app.push_screen("profile_create")
