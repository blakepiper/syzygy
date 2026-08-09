"""The Syzygy application shell.

Owns exactly three things: the collaborators every screen needs
(`SyzygyServices`), the currently selected profile, and which screen is on
top. Everything else - what a transit means, which card was drawn, what to
send a model - belongs to the layers below and is only rendered here.

Collaborators are injected rather than constructed inside screens so that
tests can run the whole ritual against a fixture astrology engine and the
`FixtureProvider`, with no network, no API key, and no ephemeris work
(docs/old/IMPLEMENTATION_PLAN.md Milestone 5).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App

from syzygy.astrology.base import AstrologyEngine
from syzygy.audio import SilentTheme, ThemePlayer
from syzygy.clock import Clock, SystemClock
from syzygy.domain.profile import Profile
from syzygy.domain.reading import Reading
from syzygy.interpretation.base import InterpretationProvider
from syzygy.storage import readings as readings_store
from syzygy.tui.animation.driver import AnimationDriver
from syzygy.tui.animation.motion import (
    MotionSettings,
    next_level,
    resolve_motion,
    save_motion_level,
)
from syzygy.tui.screens.archive import ArchiveScreen
from syzygy.tui.screens.chart import ChartScreen
from syzygy.tui.screens.cosmos import CosmosScreen
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.local_setup import LocalSetupScreen
from syzygy.tui.screens.model_setup import ModelSetupScreen
from syzygy.tui.screens.oracle_ask import OracleAskScreen
from syzygy.tui.screens.profile_create import ProfileCreateScreen
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.source_material import SourceMaterialScreen
from syzygy.tui.screens.startup import StartupScreen
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
    settings_path: Path | None = None


def default_services(database_path: Path | str | None = None) -> SyzygyServices:
    """Production wiring: real database, real clock, Kerykeion, and
    whichever `InterpretationProvider` `syzygy model use` last selected.

    The ritual must stay navigable and coherent with no model configured
    (docs/old/DESIGN.md Milestone 5, docs/old/ARCHITECTURE_HANDOFF.md section 34), so this
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

    # M16.8d: a managed local model is validated cheaply on every startup -
    # files present, sizes unchanged, versions still the ones it was
    # verified against. A broken one is a *banner*, never a crash and never
    # a silent use of an unverified artifact: the ritual falls back to
    # `FixtureProvider` exactly as it does for someone who never set a
    # model up, and `[M] → Repair local model` is the route back.
    managed_provider, managed_reason = _managed_local_provider(settings_path)
    if managed_provider is not None:
        provider, fallback_reason = managed_provider, None
    elif managed_reason is not None:
        fallback_reason = managed_reason

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
        settings_path=settings_path,
    )


def _managed_local_provider(settings_path: Path):
    """`(provider, reason)` for a configured local model.

    `(provider, None)` when it is set up and healthy, `(None, reason)`
    when it is set up but needs repair, and `(None, None)` when nothing
    local was ever configured - which is not a problem to report.

    Never raises. This runs on every start, and a subsystem that can stop
    the application from opening is worse than one that is unavailable.
    """
    try:
        from syzygy.config import default_app_paths
        from syzygy.local_models.catalog import load_catalog
        from syzygy.local_models.managed_provider import ManagedLocalProvider
        from syzygy.local_models.paths import LocalModelPaths
        from syzygy.local_models.settings import ManagementMode, load_local_model_settings
        from syzygy.local_models.verification import validate_managed_configuration

        settings = load_local_model_settings(settings_path)
        if settings.mode is not ManagementMode.MANAGED:
            return None, None

        health = validate_managed_configuration(
            settings_path, catalog_version=load_catalog().catalog_version
        )
        if not health.healthy:
            return None, f"the local model needs repair ({health.reason})"

        paths = LocalModelPaths.from_app_paths(default_app_paths())
        return ManagedLocalProvider(settings_path, paths), None
    except Exception as exc:  # noqa: BLE001 - startup must never fail here
        return None, f"the local model could not be prepared ({type(exc).__name__}: {exc})"


def stop_managed_model(provider: object) -> None:
    """Stop a managed local server, if that is what `provider` is.

    Duck-typed on purpose: `syzygy.tui` must not import the local-model
    subsystem to decide whether to call a method on it, and every other
    provider simply has no `stop`. Failures are swallowed - the
    application is already on its way out, and a supervisor that cannot
    tidy up must not turn quitting into a traceback.
    """
    stop = getattr(provider, "stop", None)
    if stop is None:
        return
    try:
        stop()
    except Exception:  # noqa: BLE001 - shutdown is best effort
        pass


class SyzygyApp(App[None]):
    """SELF + COSMOS + CHANCE, as a terminal application."""

    CSS_PATH = "syzygy.tcss"
    TITLE = "SYZYGY"

    #: Declared once here, not per-screen, so these work identically on
    #: every screen by construction (M10.2). A focused `Input` still gets
    #: first refusal at a keystroke, so typing a literal "q" or "s" into a
    #: form field is unaffected.
    BINDINGS = [
        ("q", "quit", "quit"),
        ("s", "toggle_sound", "sound"),
        ("f2", "cycle_motion", "motion"),
    ]

    SCREENS = {
        "startup": StartupScreen,
        "welcome": WelcomeScreen,
        "profile_create": ProfileCreateScreen,
        "profile_select": ProfileSelectScreen,
        "home": HomeScreen,
        "chart": ChartScreen,
        "cosmos": CosmosScreen,
        "archive": ArchiveScreen,
        "model_setup": ModelSetupScreen,
        "local_setup": LocalSetupScreen,
        "source_material": SourceMaterialScreen,
        "oracle_ask": OracleAskScreen,
        "too_small": TooSmallScreen,
    }

    def __init__(
        self,
        services: SyzygyServices,
        *,
        glyphs: GlyphSet | None = None,
        theme_player: ThemePlayer | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.glyphs = glyphs or default_glyphs()
        self.profile: Profile | None = None
        self.startup_seen = False
        #: Silent unless a caller supplies a real one. Tests and CI get
        #: silence by construction rather than by mocking a device.
        # Not `self.theme`: Textual's `App.theme` is its own colour-theme
        # name, and shadowing it breaks the app's styling.
        self.theme_player = theme_player or SilentTheme("no theme player supplied")
        self.animation_driver = AnimationDriver(self, resolve_motion(services.settings_path))
        self.animations = self.animation_driver.animations

    def on_mount(self) -> None:
        """Open the way the application is meant to open (M17.1a).

        Unconditionally the startup screen: which screen a launch *lands*
        on is `syzygy.tui.screens.startup`'s decision, made once, from the
        saved profiles - the shell no longer knows the rule, and there is
        no second copy of it to drift.
        """
        self.theme_player.start()
        self.push_screen("startup")
        self._update_size_gate(self.size.width, self.size.height)

    def on_resize(self, event: events.Resize) -> None:
        self._update_size_gate(event.size.width, event.size.height)

    def _update_size_gate(self, width: int, height: int) -> None:
        """Push/pop `TooSmallScreen` as the terminal crosses the compact
        floor (docs/old/DESIGN.md section 18.6). The screen it covers is never torn
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

    def action_toggle_sound(self) -> None:
        """Mute/unmute the theme (M15.1d).

        A visible response either way: on a build with no audio the key
        is not silently dead, it says why.
        """
        if not self.theme_player.available:
            self.bell()
            self.notify("No audio on this install.", severity="information", timeout=3)
            return
        muted = self.theme_player.toggle_mute()
        self.notify("Theme muted." if muted else "Theme unmuted.", timeout=2)

    def action_cycle_motion(self) -> None:
        """Cycle full/reduced/off and persist only the animation section."""
        current = self.animations.motion
        level = next_level(current.level)
        self.animations.animator.finish_all()
        self.animations.animator.motion = MotionSettings(level=level, speed=current.speed)
        if self.services.settings_path is not None:
            save_motion_level(self.services.settings_path, level)
        self.notify(f"Animations: {level.value}.", timeout=2)

    def on_unmount(self) -> None:
        """Release the audio device and the local model server however the
        app is ending - `[Q]`, an exception, or a signal. `run()` stops
        both again in a `finally`; both `stop()`s are idempotent and
        bounded, so quitting cannot hang on either."""
        self.theme_player.stop()
        stop_managed_model(self.services.provider)

    def set_profile(self, profile: Profile) -> None:
        self.profile = profile

    def clear_profile(self) -> None:
        """Forget the active profile (M11.2c: it was just deleted).

        Screens read `self.profile` to decide what to render and every one
        of them already handles `None`, so this is the whole of it - but it
        must happen, or the app keeps a `Profile` whose row no longer
        exists and would try to write readings against a dangling id.
        """
        self.profile = None

    def todays_reading(self) -> Reading | None:
        """Today's canonical reading for the active profile, if it exists.

        A pure read - opening the app never creates or advances a reading.
        """
        if self.profile is None:
            return None
        local_date = self.services.clock.now_utc().astimezone().date().isoformat()
        return readings_store.get_today(self.services.conn, self.profile.id, local_date)


def run(database_path: Path | str | None = None, *, audio: bool = True) -> None:
    """Launch the TUI against the local database and close it cleanly.

    The theme is stopped in a `finally`, so the device is released on a
    normal quit, on an unhandled exception, and on SIGINT alike - not only
    on the tidy path through `on_unmount`.
    """
    from syzygy.audio import create_theme_player
    from syzygy.config import default_app_paths
    from syzygy.logs import quiet_library_logging

    # First, and before anything imports a dependency that might configure
    # logging on our behalf: under a full-screen application, a stray INFO
    # line is not a log, it is damage to the frame. See `syzygy.logs`.
    quiet_library_logging()

    services = default_services(database_path)
    settings_path = (
        default_app_paths().settings_path
        if database_path is None
        else Path(database_path).with_name("settings.json")
    )
    theme = create_theme_player(settings_path, enabled=audio)
    try:
        SyzygyApp(services, theme_player=theme).run()
    finally:
        theme.stop()
        stop_managed_model(services.provider)
        services.conn.close()
