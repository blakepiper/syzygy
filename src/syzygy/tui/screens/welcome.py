"""First launch, with no self configured (docs/old/DESIGN.md section 6.1).

Since M17.1 this screen is only the first-launch *copy*. The opening
sequence and the decision about where a launch lands both moved to
`syzygy.tui.screens.startup`, which every launch passes through - this
screen used to own them, and a returning user therefore never saw a frame
of either.
"""

from __future__ import annotations

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Middle, Vertical
from textual.widgets import Footer, Static

from syzygy.storage.profiles import list_profiles
from syzygy.tui.screens.base import SyzygyScreen
from syzygy.tui.screens.model_setup import load_status
from syzygy.tui.screens.startup import route_after_startup
from syzygy.tui.widgets.brand import ASCII_WORDMARK, Logo, Mascot

#: Kept for the screens and tests that want the wordmark as plain text.
#: `Logo` renders the real thing and falls back to this.
BANNER = ASCII_WORDMARK

#: A first-launch nudge, not a gate (M10.4c/AGENTS.md: "the ritual still
#: never requires a model configured") - shown only when nothing has ever
#: been selected or stored, so a returning user who deliberately chose
#: fixture doesn't see it again.
NO_MODEL_CONFIGURED_NUDGE = (
    "No model configured — press [M] to set one up, or continue with sample readings."
)


class WelcomeScreen(SyzygyScreen):
    """`SELF` is the first point of the alignment; nothing else can
    resolve until a profile exists."""

    BINDINGS = [("n", "create_profile", "create profile"), ("m", "model", "model")]

    def compose(self) -> ComposeResult:
        with Middle():
            with Vertical(id="welcome-brand"):
                yield Logo(id="welcome-logo")
                yield Mascot(id="welcome-mascot")
                with Vertical(id="welcome-body"):
                    yield Static("No self is configured.", classes="lede")
                    yield Static(
                        "SELF · COSMOS · CHANCE\nThe alignment waits for you.",
                        classes="muted",
                    )
                    yield Static("", id="welcome-model-nudge", classes="muted", markup=False)
                    yield Static("", id="welcome-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render_keys()
        self._check_model_configured()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("q", "m", "n"):
            return
        if event.key in ("up", "down", "left", "right", "tab", "shift+tab"):
            # Focus movement (M17.5) is not "continue"; let the base
            # screen's bindings have it.
            return
        event.stop()
        self.action_continue()

    def action_continue(self) -> None:
        """Past the welcome copy.

        Nearly the startup routing, with one difference that is the whole
        point of this screen: with nothing saved, "continue" means *make a
        self*, not "show the welcome copy again".
        """
        if not list_profiles(self.syzygy.services.conn):
            self.app.push_screen("profile_create")
            return
        route_after_startup(self.syzygy)

    def _render_keys(self) -> None:
        """The key line, including the mute toggle when there is sound to
        mute (M15.1d). A build with no audio does not advertise a key that
        would do nothing."""
        keys = ["PRESS ANY KEY TO CONTINUE", "[N] Create profile", "[M] Model"]
        if self.syzygy.theme_player.available:
            keys.append("[S] Sound")
        keys.append("[Q] Quit")
        self.query_one("#welcome-keys", Static).update("     ".join(keys))

    @work(thread=True, exclusive=True)
    def _check_model_configured(self) -> None:
        try:
            status = load_status()
        except ImportError:
            # The `providers` extra isn't installed - fixture is the only
            # provider that can possibly be active, so there's nothing to
            # nudge about.
            return
        configured = (
            status.active_provider_id != "fixture"
            or status.openai_key_source is not None
            or status.anthropic_key_source is not None
        )
        if not configured:
            self.app.call_from_thread(self._show_nudge)

    def _show_nudge(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#welcome-model-nudge", Static).update(NO_MODEL_CONFIGURED_NUDGE)

    def action_create_profile(self) -> None:
        self.app.push_screen("profile_create")

    def action_model(self) -> None:
        self.app.push_screen("model_setup")
