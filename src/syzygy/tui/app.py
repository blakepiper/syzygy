"""The Syzygy application shell.

Owns exactly three things: the collaborators every screen needs
(`SyzygyServices`), the currently selected profile, and which screen is on
top. Everything else - what a transit means, which card was drawn, what to
send a model - belongs to the layers below and is only rendered here.

Collaborators are injected rather than constructed inside screens so that
tests can run the whole ritual against a fixture astrology engine and the
`FixtureProvider`, with no network, no API key, and no ephemeris work
(IMPLEMENTATION_PLAN.md Milestone 5).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App

from syzygy.astrology.base import AstrologyEngine
from syzygy.clock import Clock, SystemClock
from syzygy.domain.profile import Profile
from syzygy.domain.reading import Reading
from syzygy.interpretation.base import InterpretationProvider
from syzygy.storage import readings as readings_store
from syzygy.storage.profiles import list_profiles
from syzygy.tui.screens.archive import ArchiveScreen
from syzygy.tui.screens.chart import ChartScreen
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.model_setup import ModelSetupScreen
from syzygy.tui.screens.profile_create import ProfileCreateScreen
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.too_small import MIN_HEIGHT, MIN_WIDTH, TooSmallScreen
from syzygy.tui.screens.welcome import WelcomeScreen
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs

if TYPE_CHECKING:
    from textual import events


@dataclass
class SyzygyServices:
    """Everything the interface is allowed to reach outside itself."""

    conn: sqlite3.Connection
    clock: Clock
    astrology: AstrologyEngine
    provider: InterpretationProvider


def default_services(database_path: Path | str | None = None) -> SyzygyServices:
    """Production wiring: real database, real clock, Kerykeion, and
    whichever `InterpretationProvider` `syzygy model use` last selected.

    The ritual must stay navigable and coherent with no model configured
    (DESIGN.md Milestone 5, ARCHITECTURE_HANDOFF.md section 34), so this
    never fails to produce a provider: `resolve_selected_provider` falls
    back to `FixtureProvider` for a missing selection, a missing API key,
    or any other reason the saved choice can't be built, and this prints
    that reason to stderr rather than raising or hiding it.
    """
    import sys

    from syzygy.astrology.kerykeion_backend import KerykeionAstrologyEngine
    from syzygy.config import default_app_paths
    from syzygy.interpretation.providers.selection import load_selection, resolve_selected_provider
    from syzygy.storage.database import open_database

    if database_path is None:
        paths = default_app_paths()
        paths.ensure_exists()
        database_path = paths.database_path
        settings_path = paths.settings_path
    else:
        # A caller supplying its own database path (a test, most likely)
        # gets an equally isolated settings file next to it, rather than
        # this reading the real machine's global settings.json.
        settings_path = Path(database_path).with_name("settings.json")

    provider, fallback_reason = resolve_selected_provider(load_selection(settings_path))
    if fallback_reason:
        print(
            f"syzygy: {fallback_reason} - using the fixture provider instead", file=sys.stderr
        )

    return SyzygyServices(
        # The TUI's thread workers touch this connection from a worker
        # thread; they are declared exclusive and never overlap.
        conn=open_database(database_path, check_same_thread=False),
        clock=SystemClock(),
        astrology=KerykeionAstrologyEngine(),
        provider=provider,
    )


class SyzygyApp(App[None]):
    """SELF + COSMOS + CHANCE, as a terminal application."""

    CSS_PATH = "syzygy.tcss"
    TITLE = "SYZYGY"

    #: Declared once here, not per-screen, so quit works identically on
    #: every screen by construction (M10.2). A focused `Input` still gets
    #: first refusal at a keystroke, so typing a literal "q" into a form
    #: field is unaffected.
    BINDINGS = [("q", "quit", "quit")]

    SCREENS = {
        "welcome": WelcomeScreen,
        "profile_create": ProfileCreateScreen,
        "profile_select": ProfileSelectScreen,
        "home": HomeScreen,
        "chart": ChartScreen,
        "archive": ArchiveScreen,
        "model_setup": ModelSetupScreen,
        "too_small": TooSmallScreen,
    }

    def __init__(
        self,
        services: SyzygyServices,
        *,
        glyphs: GlyphSet | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.glyphs = glyphs or default_glyphs()
        self.profile: Profile | None = None

    def on_mount(self) -> None:
        profiles = list_profiles(self.services.conn)
        if not profiles:
            self.push_screen("welcome")
        elif len(profiles) == 1:
            self.set_profile(profiles[0])
            self.push_screen("home")
        else:
            self.push_screen("profile_select")
        self._update_size_gate(self.size.width, self.size.height)

    def on_resize(self, event: events.Resize) -> None:
        self._update_size_gate(event.size.width, event.size.height)

    def _update_size_gate(self, width: int, height: int) -> None:
        """Push/pop `TooSmallScreen` as the terminal crosses the compact
        floor (DESIGN.md section 18.6). The screen it covers is never torn
        down - popping restores it exactly, so a mid-ritual state like an
        in-progress Wheel draw survives a shrink-then-grow round trip.
        """
        current = self.screen
        too_small = width < MIN_WIDTH or height < MIN_HEIGHT
        if too_small and not isinstance(current, TooSmallScreen):
            self.push_screen("too_small")
        elif not too_small and isinstance(current, TooSmallScreen):
            self.pop_screen()
        elif too_small and isinstance(current, TooSmallScreen):
            # Already showing - update the reported size rather than
            # re-pushing. A freshly pushed screen sets its own initial
            # text from `on_mount`, once it has actually mounted.
            current.update_size(width, height)

    def set_profile(self, profile: Profile) -> None:
        self.profile = profile

    def todays_reading(self) -> Reading | None:
        """Today's canonical reading for the active profile, if it exists.

        A pure read - opening the app never creates or advances a reading.
        """
        if self.profile is None:
            return None
        local_date = self.services.clock.now_utc().astimezone().date().isoformat()
        return readings_store.get_today(self.services.conn, self.profile.id, local_date)


def run(database_path: Path | str | None = None) -> None:
    """Launch the TUI against the local database and close it cleanly."""
    services = default_services(database_path)
    try:
        SyzygyApp(services).run()
    finally:
        services.conn.close()
