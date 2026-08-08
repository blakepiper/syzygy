"""First launch, with no self configured (DESIGN.md section 6.1)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Middle, Vertical
from textual.widgets import Footer, Static

from syzygy.tui.screens.base import SyzygyScreen
from syzygy.tui.screens.model_setup import load_status
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
            with Center():
                yield Logo(id="welcome-logo")
            with Center():
                with Horizontal(id="welcome-columns"):
                    yield Mascot(id="welcome-mascot")
                    with Vertical(id="welcome-body"):
                        yield Static("No self is configured.", classes="lede")
                        yield Static(
                            "A reading needs a natal chart. Nothing is calculated,\n"
                            "drawn, or interpreted before one exists.",
                            classes="muted",
                        )
                        yield Static("", id="welcome-model-nudge", classes="muted", markup=False)
                        yield Static("", id="welcome-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render_keys()
        self._check_model_configured()

    def _render_keys(self) -> None:
        """The key line, including the mute toggle when there is sound to
        mute (M15.1d). A build with no audio does not advertise a key that
        would do nothing."""
        keys = ["[N] Create profile", "[M] Model"]
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
