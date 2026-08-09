"""Today's cosmos - the full sky, against the natal chart (M13.1).

The counterpart to `screens/chart.py`: where that screen is SELF in full,
this is COSMOS in full. `HomeScreen` shows the top three transits as
badges beside the alignment axis; this shows every transit that survived
Syzygy's orb policy, in rank order, with the natal point each one touches.

Two invariants shape what is (and is not) here:

- **Nothing on this screen is ranked here.** `rank_current_transits`
  composes engine -> `syzygy.astrology.policy` -> `syzygy.astrology.ranking`
  and hands back a decided order; the screen renders that order and never
  scores, sorts or filters anything itself (AGENTS.md: Syzygy owns transit
  significance, and it owns it in one place).
- **No current-location astrology** (DESIGN.md section 3.2). A
  `TransitSnapshot` carries transiting positions and aspects to natal
  points, and that is all this screen has to draw from - there is no
  current latitude/longitude, no current houses, and no current
  Ascendant/Midheaven anywhere in the data or in the rendering below.
  Where "Ascendant" or "Midheaven" appears it is a *natal* angle being
  transited.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Static

from syzygy.domain.astrology import RankedTransit, TransitSnapshot
from syzygy.domain.interpretation import InterpretationKind, SummaryResult
from syzygy.storage.reading_service import rank_current_transits
from syzygy.storage.summaries import get_summary
from syzygy.storage.summary_service import cosmos_summary
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.glyph import format_degrees, format_orb


class CosmosScreen(SyzygyScreen):
    BINDINGS = [("g", "summary", "summary"), ("escape", "back", "back")]

    def __init__(self) -> None:
        super().__init__()
        self._ranked: list[RankedTransit] | None = None

    def compose(self) -> ComposeResult:
        """Positions and transits as two lists, side by side when there is
        room - the same arrangement `ChartScreen` uses, for the same
        reason (M12.5): stacked, the ranked transits that are the point of
        the screen sit below the fold.
        """
        yield TitleBar("TODAY'S SKY")
        with Horizontal(id="cosmos-columns"):
            yield VerticalScroll(Static("", id="cosmos-sky-body"), id="cosmos-sky")
            yield VerticalScroll(Static("", id="cosmos-transits-body"), id="cosmos-transits")
        yield Static("[G] Generate today's summary", id="cosmos-summary", classes="summary-panel")
        yield Footer()

    def on_mount(self) -> None:
        if self.syzygy.profile is None:
            self._sky_body.update("No profile is selected.")
            self._transits_body.update("")
            return
        self._sky_body.update("Calculating today's sky...")
        self._transits_body.update("")
        self._load_sky()

    # -- data --------------------------------------------------------------

    @work(thread=True, exclusive=True, group="cosmos")
    def _load_sky(self) -> None:
        """The ephemeris call is slow enough to stutter the interface, so
        it runs off the event loop - the pattern `HomeScreen._load_sky`
        already uses.
        """
        profile = self.syzygy.profile
        if profile is None:
            return
        services = self.syzygy.services
        try:
            snapshot, ranked = rank_current_transits(
                profile, services.astrology, services.clock.now_utc()
            )
        except Exception as exc:  # DESIGN.md section 23: never continue silently
            self.app.call_from_thread(self._failed, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._resolved, snapshot, ranked)

    def _resolved(self, snapshot: TransitSnapshot, ranked: list[RankedTransit]) -> None:
        if not self.is_mounted:  # the user navigated away mid-calculation
            return
        self._sky_body.update("\n".join(self._sky_lines(snapshot)))
        self._transits_body.update("\n".join(self._transit_lines(snapshot, ranked)))
        self._ranked = ranked
        profile = self.syzygy.profile
        if profile is not None:
            local_date = (
                snapshot.instant_utc.astimezone(ZoneInfo(profile.birth_data.timezone))
                .date()
                .isoformat()
            )
            cached = get_summary(
                self.syzygy.services.conn,
                profile.id,
                InterpretationKind.COSMOS_SUMMARY,
                local_date,
            )
            if cached is not None:
                self._show_summary(cached)

    def _failed(self, message: str) -> None:
        if not self.is_mounted:
            return
        self._sky_body.update(
            f"Sky calculation failed - {message}\n\n"
            f"Nothing here is cached: press [Escape] and open the screen again to retry."
        )
        self._transits_body.update("")

    def action_summary(self) -> None:
        if self.syzygy.profile is None or self._ranked is None:
            self.app.bell()
            self.query_one("#cosmos-summary", Static).update(
                "Today's sky must finish resolving before it can be summarized."
            )
            return
        self.query_one("#cosmos-summary", Static).update("Interpreting today's sky…")
        self._generate_summary()

    @work(exclusive=True, group="cosmos-summary")
    async def _generate_summary(self) -> None:
        profile = self.syzygy.profile
        ranked = self._ranked
        if profile is None or ranked is None:
            return
        services = self.syzygy.services
        try:
            result = await cosmos_summary(
                services.conn,
                profile,
                ranked,
                services.provider,
                services.clock.now_utc(),
            )
        except Exception as exc:
            self._summary_failed(f"{type(exc).__name__}: {exc}")
            return
        self._show_summary(result)

    def _show_summary(self, result: SummaryResult) -> None:
        if self.is_mounted:
            self.query_one("#cosmos-summary", Static).update(
                f"{result.headline}\n\n{result.body}\n\n[G] Show cached summary"
            )

    def _summary_failed(self, message: str) -> None:
        if self.is_mounted:
            self.query_one("#cosmos-summary", Static).update(
                f"Summary unavailable — {message}\n[G] Retry"
            )

    # -- rendering ---------------------------------------------------------

    def _sky_lines(self, snapshot: TransitSnapshot) -> list[str]:
        """Where the bodies actually are, right now.

        Sign and degree only. A transiting body has no house here and
        cannot be given one: houses need a location, and the only location
        Syzygy knows is the birthplace on the natal chart.
        """
        glyphs = self.syzygy.glyphs
        local = snapshot.instant_utc.astimezone()
        lines = [
            self.syzygy.profile.display_name if self.syzygy.profile else "",
            f"{local.strftime('%Y-%m-%d %H:%M')} local  ({snapshot.instant_utc:%H:%M} UTC)",
            f"orb policy {snapshot.astrology_policy_version}",
            "",
            "POSITIONS",
            "",
        ]
        for position in snapshot.transiting_positions:
            retrograde = " ℞" if position.retrograde else ""  # as `ChartScreen` marks it
            lines.append(
                f"  {glyphs.body(position.body):<3} {position.body:<10} "
                f"{glyphs.sign(position.sign)} {position.sign:<12} "
                f"{format_degrees(position.longitude):>8}{retrograde}"
            )
        return lines

    def _transit_lines(self, snapshot: TransitSnapshot, ranked: list[RankedTransit]) -> list[str]:
        """The ranked set, in the order it was handed over.

        Each entry names the natal point it touches, because that is what
        makes a transit *this* person's rather than the day's.
        """
        glyphs = self.syzygy.glyphs
        lines = [
            f"{len(ranked)} significant transits",
            f"of {len(snapshot.raw_aspects)} calculated - the rest fall outside the orb policy",
            "",
        ]
        if not ranked:
            lines.append("  Nothing is close enough to count today.")
            return lines
        for transit in ranked:
            aspect = transit.aspect
            lines.extend(
                [
                    f"  {transit.rank}. {glyphs.body(aspect.transiting_body):<3} "
                    f"{glyphs.aspect(aspect.aspect):<3} {glyphs.body(aspect.natal_target):<3} "
                    f"transiting {aspect.transiting_body} {aspect.aspect} "
                    f"natal {aspect.natal_target}",
                    f"     {format_orb(aspect.orb_degrees)} {aspect.movement}",
                    "",
                ]
            )
        return lines

    @property
    def _sky_body(self) -> Static:
        return self.query_one("#cosmos-sky-body", Static)

    @property
    def _transits_body(self) -> Static:
        return self.query_one("#cosmos-transits-body", Static)

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
