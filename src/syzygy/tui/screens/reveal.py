"""The reveal (DESIGN.md section 14, ARCHITECTURE_HANDOFF.md section 33).

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

#: Seconds between stages. Short enough to stay a reveal rather than a
#: loading screen; any key skips to the reading.
STAGE_INTERVAL = 0.45


class RevealScreen(SyzygyScreen):
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
        self.set_timer(STAGE_INTERVAL, self._stage_card)

    def _stage_card(self) -> None:
        if self.reading.card_draw is None:
            return
        card_widget = self.query_one("#reveal-card", TarotCardWidget)
        card_widget.set_card(get_card(self.reading.card_draw.card_id))
        card_widget.styles.opacity = 0.0
        card_widget.styles.animate("opacity", value=1.0, duration=0.35)
        self.query_one("#reveal-alignment", AlignmentWidget).chance_resolved = True
        self.set_timer(STAGE_INTERVAL, self._stage_transits)

    def _stage_transits(self) -> None:
        context = self.reading.interpretation_context
        transits = list(context.significant_transits) if context is not None else []
        container = self.query_one("#reveal-transits", Horizontal)
        for index, transit in enumerate(transits[:4]):
            self.set_timer(
                index * 0.12,
                lambda transit=transit: container.mount(
                    TransitBadge(transit, glyphs=self.syzygy.glyphs)
                ),
            )
        self.query_one("#reveal-caption", Static).update(
            "SELF, COSMOS, and CHANCE are aligned. The result is fixed."
        )
        self.set_timer(STAGE_INTERVAL, self._stage_done)

    def _stage_done(self) -> None:
        self.query_one("#reveal-hint", Static).update("[ENTER] read the alignment   [Q] QUIT")
        self.set_timer(STAGE_INTERVAL * 2, self.action_read)

    def action_read(self) -> None:
        if self._advanced:
            return
        self._advanced = True
        from syzygy.tui.screens.reading import ReadingScreen

        self.app.switch_screen(ReadingScreen(self.reading))
