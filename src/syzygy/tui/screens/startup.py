"""The opening sequence, and the one place that decides where a launch
lands (M17.1).

Before this screen existed, `SyzygyApp.on_mount` routed straight to
`home` or `profile_select` when a profile was saved, and the startup
choreography was only ever played by `WelcomeScreen` - a screen a
returning user never sees. So the wordmark, the logo, the mascot and every
frame of the sequence existed and were unreachable on the path almost
every launch takes.

Two things are true at once here, and the second is the important one:

* the sequence plays on **every** launch, so the application opens the
  way it was designed to open;
* it is **never** a gate. Any keypress finishes it immediately, motion
  `off` skips it entirely, and where the launch routes to does not depend
  on a single frame having been drawn. `docs/animation.md` section 1.3:
  input must never wait on animation.

The profile-count routing lives here and nowhere else. `WelcomeScreen`
calls into it for the case where a profile has just been created; the app
shell no longer knows the rule at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.widgets import Static

from syzygy.storage.profiles import list_profiles
from syzygy.tui.screens.base import SyzygyScreen
from syzygy.tui.widgets.brand import Logo, Mascot

if TYPE_CHECKING:
    from syzygy.tui.app import SyzygyApp


def route_after_startup(app: SyzygyApp) -> None:
    """Where a launch lands, given what is saved.

    No profile means the welcome copy, one means straight to the day, and
    several means choosing which self is being read for - which self it is
    is never picked for the user (`profile_select`'s own rule).
    """
    profiles = list_profiles(app.services.conn)
    if not profiles:
        app.switch_screen("welcome")
    elif len(profiles) == 1:
        app.set_profile(profiles[0])
        app.switch_screen("home")
    else:
        app.switch_screen("profile_select")


class StartupScreen(SyzygyScreen):
    """Mark, logo, mascot - then wherever this launch belongs."""

    #: This screen *is* a choreography; the default staggered entry would
    #: fade in the very widgets the sequence is about to reveal.
    SCREEN_TRANSITIONS = False

    def __init__(self) -> None:
        super().__init__()
        self._routed = False

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Static("", id="startup-mark", classes="startup-mark")
                yield Logo(id="startup-logo")
            with Center():
                yield Mascot(id="startup-mascot")

    def on_mount(self) -> None:
        self._begin()

    def on_screen_resume(self) -> None:
        # Deliberately not `super()`: this screen has no title bar and no
        # regions to stagger, and `_update_size_classes` is all it wants
        # from the base. The resume path matters because the too-small
        # gate can be pushed on top of this screen at launch - the gate
        # wins, and the sequence waits until there is a terminal to play
        # it in (M17.1d).
        self._update_size_classes()
        # Textual keeps one instance per installed screen name, so this
        # screen can be arrived at a second time carrying the state of the
        # first. Whatever it routed to last time is finished business.
        self._routed = False
        self._begin()

    def _begin(self) -> None:
        if self._routed or self.app.screen is not self:
            return
        animator = self.syzygy.animations.animator
        if animator.handle_for("startup") is not None:
            return  # already playing

        if self.syzygy.startup_seen:
            # A second startup within one process (M17.1c) - the sequence
            # is an opening, and openings do not repeat.
            self._route()
            return
        self.syzygy.animations.startup(
            self.query_one("#startup-mark", Static),
            self.query_one("#startup-logo", Logo),
            self.query_one("#startup-mascot", Mascot),
            self._route,
        )

    def on_key(self, event: events.Key) -> None:
        """Any key finishes the sequence and routes at once.

        `finish_all` rather than a second skip path of its own: landing
        every running timeline on its final state is exactly what the
        completion would have done, so skipping and waiting reach the same
        screen with the same state (M17.1b).
        """
        if event.key == "q":
            return  # the app-level quit binding still has to work
        event.stop()
        self.syzygy.animations.animator.finish_all()

    def _route(self) -> None:
        if self._routed:
            return
        self.syzygy.startup_seen = True
        if self.app.screen is not self:
            # Something sits on top of the opening - the too-small gate at
            # launch, most likely. `switch_screen` replaces whatever is on
            # top, so routing from underneath would throw *that* screen
            # away. Wait to be the top screen again; `on_screen_resume`
            # comes back through here.
            return
        self._routed = True
        route_after_startup(self.syzygy)
