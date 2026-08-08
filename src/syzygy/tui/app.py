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
from syzygy.tui.screens.profile_create import ProfileCreateScreen
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.welcome import WelcomeScreen
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs


@dataclass
class SyzygyServices:
    """Everything the interface is allowed to reach outside itself."""

    conn: sqlite3.Connection
    clock: Clock
    astrology: AstrologyEngine
    provider: InterpretationProvider


def default_services(database_path: Path | str | None = None) -> SyzygyServices:
    """Production wiring: real database, real clock, Kerykeion, and - for
    now - the fixture interpretation provider.

    Milestone 5 deliberately ships with `FixtureProvider`: the whole ritual
    must be navigable and coherent with no model configured
    (DESIGN.md Milestone 5, ARCHITECTURE_HANDOFF.md section 34). Real
    providers arrive in Milestone 7 and replace only this line.
    """
    from syzygy.astrology.kerykeion_backend import KerykeionAstrologyEngine
    from syzygy.config import default_app_paths
    from syzygy.interpretation.providers.fixture import FixtureProvider
    from syzygy.storage.database import open_database

    if database_path is None:
        paths = default_app_paths()
        paths.ensure_exists()
        database_path = paths.database_path

    return SyzygyServices(
        # The TUI's thread workers touch this connection from a worker
        # thread; they are declared exclusive and never overlap.
        conn=open_database(database_path, check_same_thread=False),
        clock=SystemClock(),
        astrology=KerykeionAstrologyEngine(),
        provider=FixtureProvider(),
    )


class SyzygyApp(App[None]):
    """SELF + COSMOS + CHANCE, as a terminal application."""

    CSS_PATH = "syzygy.tcss"
    TITLE = "SYZYGY"

    SCREENS = {
        "welcome": WelcomeScreen,
        "profile_create": ProfileCreateScreen,
        "profile_select": ProfileSelectScreen,
        "home": HomeScreen,
        "chart": ChartScreen,
        "archive": ArchiveScreen,
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
