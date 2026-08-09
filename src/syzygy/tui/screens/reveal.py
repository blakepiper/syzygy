"""The reveal (docs/old/DESIGN.md section 14, docs/old/ARCHITECTURE_HANDOFF.md section 33).

The card is already committed to storage by the time this screen exists -
the sequence below is presentation of a fixed result, in the fixed order
the ritual requires:

    card reveal -> title and correspondence -> transits attach ->
    SELF/COSMOS/CHANCE align -> interpretation begins

This ordering is product logic, not decoration; do not collapse it into a
single immediate render.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.widgets import Footer, Static

from syzygy.domain.reading import Reading
from syzygy.sortes.deck import get_card
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.alignment import AlignmentWidget
from syzygy.tui.widgets.tarot_card import TarotCardWidget
from syzygy.tui.widgets.transit_badge import TransitBadge


class RevealScreen(SyzygyScreen):
    #: The reveal owns its own staged choreography (`ritual_reveal`);
    #: the default screen entry would animate the same widgets twice.
    SCREEN_TRANSITIONS = False

    BINDINGS = [
        ("enter", "read", "read"),
        ("space", "read", "read"),
        ("escape", "read", "read"),
    ]

    def __init__(self, reading: Reading) -> None:
        super().__init__()
        self.reading = reading
        self._advanced = False

    def compose(self) -> ComposeResult:
        yield TitleBar("THE ALIGNMENT")
        # Directly under the title, the same place `HomeScreen` puts it -
        # the axis is one motif across the app, not per-screen furniture.
        yield AlignmentWidget(id="reveal-alignment")
        yield Static("", id="reveal-particles", classes="particles")
        # The slack belongs to `#reveal-stage`, not to the card: a `1fr`
        # card with a `max-height` had Textual reserve the full remainder
        # for it and then place the caption and the key hint past the
        # bottom edge on a tall terminal. The wrapper takes the slack and
        # the card fills the wrapper, which also gets the card centred -
        # a `Static` sibling is full-width, so `align-horizontal` on the
        # body had nothing to centre the card against.
        with Vertical(id="reveal-body"):
            with Center(id="reveal-stage"):
                yield TarotCardWidget(glyphs=self.syzygy.glyphs, id="reveal-card")
            yield Static("", id="reveal-caption", classes="muted")
            with Horizontal(id="reveal-transits"):
                pass
            yield Static("", id="reveal-hint", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        alignment = self.query_one("#reveal-alignment", AlignmentWidget)
        alignment.self_resolved = True
        alignment.cosmos_resolved = True
        # Quit is discoverable from the first frame - the rest of the hint
        # (any key skips the staged reveal) fills in once staging finishes.
        self.query_one("#reveal-hint", Static).update("[Q] QUIT")
        self.syzygy.animations.draw_complete(
            self.query_one("#reveal-particles", Static), self._start_stages
        )

    def _start_stages(self) -> None:
        if self.is_mounted and not self._advanced:
            self.syzygy.animations.ritual_reveal(
                self._stage_card, self._stage_transits, self._stage_done, self.action_read
            )

    def _stage_card(self) -> None:
        if self.reading.card_draw is None:
            return
        card_widget = self.query_one("#reveal-card", TarotCardWidget)
        card_widget.set_card(get_card(self.reading.card_draw.card_id))
        self.syzygy.animations.trigger("enter", card_widget)
        self.query_one("#reveal-alignment", AlignmentWidget).chance_resolved = True

    def _stage_transits(self) -> None:
        context = self.reading.interpretation_context
        transits = list(context.significant_transits) if context is not None else []
        container = self.query_one("#reveal-transits", Horizontal)
        badges = [
            TransitBadge(transit, glyphs=self.syzygy.glyphs) for transit in transits[:4]
        ]
        for badge in badges:
            badge.styles.opacity = 0.0
            container.mount(badge)
        self.syzygy.animations.enter_staggered(badges)
        self.query_one("#reveal-caption", Static).update(
            "SELF, COSMOS, and CHANCE are aligned. The result is fixed."
        )

    def _stage_done(self) -> None:
        self.query_one("#reveal-hint", Static).update("[ENTER] read the alignment   [Q] QUIT")

    def action_read(self) -> None:
        if self._advanced:
            return
        self._advanced = True
        self.syzygy.animations.animator.cancel("ritual-reveal")
        from syzygy.tui.screens.reading import ReadingScreen

        self.app.switch_screen(ReadingScreen(self.reading))
