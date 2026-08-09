"""The natal chart inspector (docs/old/DESIGN.md section 6.2's "detailed chart
inspector remains available separately").

Renders the saved chart verbatim. Nothing here recalculates: a profile's
chart is calculated once, at creation, from the birth data stored beside
it.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Static

from syzygy.domain.astrology import sign_for_longitude
from syzygy.domain.interpretation import InterpretationKind, SummaryResult
from syzygy.storage.summaries import NATAL_SCOPE_DATE, get_summary
from syzygy.storage.summary_service import natal_summary
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.glyph import format_degrees


class ChartScreen(SyzygyScreen):
    BINDINGS = [("g", "summary", "summary"), ("escape", "back", "back")]

    def compose(self) -> ComposeResult:
        """Placements and aspects as two lists, side by side when there is
        room (M12.5).

        They are two lists at every size - stacking them in one scroller
        was what left a wide terminal three-quarters empty with the aspects
        below the fold. `syzygy.tcss` puts them in columns at `-wide` and
        back in one scroller below it.
        """
        yield TitleBar("NATAL CHART")
        with Horizontal(id="chart-columns"):
            yield VerticalScroll(Static("", id="chart-body"), id="chart-placements")
            yield VerticalScroll(Static("", id="chart-aspects-body"), id="chart-aspects")
        yield Static("[G] Generate chart summary", id="chart-summary", classes="summary-panel")
        yield Footer()

    def on_mount(self) -> None:
        profile = self.syzygy.profile
        body = self.query_one("#chart-body", Static)
        aspects_body = self.query_one("#chart-aspects-body", Static)
        if profile is None:
            body.update("No profile is selected.")
            aspects_body.update("")
            return

        glyphs = self.syzygy.glyphs
        natal = profile.natal_chart
        birth = profile.birth_data
        lines = [
            profile.display_name,
            f"{birth.local_date} {birth.local_time}  {birth.place_label}",
            f"{birth.timezone}  {natal.zodiac_type}  {birth.house_system} houses",
            f"{natal.astrology_engine} {natal.astrology_engine_version}",
            "",
        ]
        for placement in natal.placements:
            house = f"house {placement.house:>2}" if placement.house else "        "
            retrograde = " ℞" if placement.retrograde else ""
            lines.append(
                f"  {glyphs.body(placement.body):<3} {placement.body:<10} "
                f"{glyphs.sign(placement.sign)} {placement.sign:<12} "
                f"{format_degrees(placement.longitude):>8}  {house}{retrograde}"
            )
        for label, longitude in (
            ("Ascendant", natal.ascendant_longitude),
            ("Midheaven", natal.midheaven_longitude),
        ):
            sign = sign_for_longitude(longitude)
            lines.append(
                f"  {glyphs.body(label):<3} {label:<10} {glyphs.sign(sign)} {sign:<12} "
                f"{format_degrees(longitude):>8}"
            )

        body.update("\n".join(lines))

        aspect_lines = [f"{len(natal.aspects)} natal aspects", ""]
        for aspect in natal.aspects:
            aspect_lines.append(
                f"  {glyphs.body(aspect.body_a):<3} {glyphs.aspect(aspect.aspect):<3} "
                f"{glyphs.body(aspect.body_b):<3} {aspect.body_a} {aspect.aspect} "
                f"{aspect.body_b} ({aspect.orb_degrees:.2f}°)"
            )
        aspects_body.update("\n".join(aspect_lines))
        cached = get_summary(
            self.syzygy.services.conn,
            profile.id,
            InterpretationKind.NATAL_SUMMARY,
            NATAL_SCOPE_DATE,
        )
        if cached is not None:
            self._show_summary(cached)

    def action_summary(self) -> None:
        if self.syzygy.profile is None:
            self.app.bell()
            return
        self.query_one("#chart-summary", Static).update("Interpreting the natal chart…")
        self._generate_summary()

    @work(exclusive=True, group="chart-summary")
    async def _generate_summary(self) -> None:
        profile = self.syzygy.profile
        if profile is None:
            return
        services = self.syzygy.services
        try:
            result = await natal_summary(
                services.conn, profile, services.provider, services.clock.now_utc()
            )
        except Exception as exc:
            self._summary_failed(f"{type(exc).__name__}: {exc}")
            return
        self._show_summary(result)

    def _show_summary(self, result: SummaryResult) -> None:
        if self.is_mounted:
            self.query_one("#chart-summary", Static).update(
                f"{result.headline}\n\n{result.body}\n\n[G] Show cached summary"
            )

    def _summary_failed(self, message: str) -> None:
        if self.is_mounted:
            self.query_one("#chart-summary", Static).update(
                f"Summary unavailable — {message}\n[G] Retry"
            )

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
