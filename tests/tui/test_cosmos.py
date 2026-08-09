"""Today's cosmos screen (M13.1).

The home screen truncates the sky to three badges; this screen is the
whole of it. What the tests pin down is that the screen *renders a ranking
it was handed* rather than deciding anything: it shows the ranked set in
the order given, it says so when the calculation fails instead of showing
an empty list, and it never asks the astrology engine for anything a
current location would be needed for.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.widgets import Static

from syzygy.clock import FixedClock
from syzygy.domain.astrology import BirthData, NatalChart, TransitSnapshot
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.tui.app import SyzygyApp, SyzygyServices
from syzygy.tui.screens.cosmos import CosmosScreen
from syzygy.tui.screens.home import HomeScreen

from .conftest import FIXED_NOW, FixtureAstrologyEngine
from .test_ritual_flow import q, settle, text_of


def app_with(conn, engine) -> SyzygyApp:
    """The standard app, with one collaborator swapped: these tests differ
    only in how the astrology engine behaves."""
    return SyzygyApp(
        SyzygyServices(
            conn=conn, clock=FixedClock(FIXED_NOW), astrology=engine, provider=FixtureProvider()
        )
    )


def bodies(pilot) -> tuple[str, str]:
    return text_of(q(pilot, "#cosmos-sky-body", Static)), text_of(
        q(pilot, "#cosmos-transits-body", Static)
    )


async def open_cosmos(pilot) -> None:
    await pilot.press("t")
    await settle(pilot)
    assert isinstance(pilot.app.screen, CosmosScreen)


# -- the binding ------------------------------------------------------------


async def test_t_opens_todays_sky_and_escape_returns(app: SyzygyApp, profile):
    """`[C]` is the chart, so the cosmos gets `[T]` - and it behaves like
    every other secondary screen on the way back out (M10.2)."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_the_key_is_advertised_on_the_home_screen(app: SyzygyApp, profile):
    """A binding nobody can see is a binding nobody uses - the hint sits in
    the COSMOS column, beside the transits it expands on."""
    async with app.run_test() as pilot:
        await settle(pilot)
        assert "[T]" in text_of(q(pilot, "#home-sky-hint", Static))


# -- what it renders --------------------------------------------------------


async def test_it_renders_the_full_ranked_set(app: SyzygyApp, profile):
    """Both transits that pass the orb policy, with orb, movement and the
    natal point each one touches - not the three-badge truncation."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        sky, transits = bodies(pilot)

        assert "2 significant transits" in transits
        # Saturn square natal Venus, applying, 0°48'.
        assert "transiting Saturn square natal Venus" in transits
        assert "0°48' applying" in transits
        assert "transiting Mars trine natal Sun" in transits
        assert "separating" in transits
        # The rank order it was handed, top first.
        assert transits.index("Saturn") < transits.index("Mars")
        # And where the bodies actually are, as the reference beside it.
        assert "Saturn" in sky and "Aries" in sky


async def test_it_shows_ranks_in_the_order_the_ranker_gave(app: SyzygyApp, profile):
    """The screen must not sort, score or filter - it numbers what it is
    handed, using each transit's own `rank`."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        _, transits = bodies(pilot)

        assert "1." in transits and "2." in transits
        assert transits.index("1.") < transits.index("2.")


async def test_it_names_the_filtered_aspects_it_is_not_showing(app: SyzygyApp, profile):
    """Three aspects are calculated and one falls outside the orb policy.
    Silently showing two would read as "the sky is quiet"."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        _, transits = bodies(pilot)

        assert "of 3 calculated" in transits


# -- the states that are not a full sky -------------------------------------


async def test_no_profile_says_so(services: SyzygyServices):
    """Reachable directly by screen name, with no profile selected."""
    async with SyzygyApp(services).run_test() as pilot:
        await settle(pilot)
        pilot.app.push_screen("cosmos")
        await settle(pilot)

        sky, transits = bodies(pilot)
        assert "No profile is selected." in sky
        assert transits == ""


async def test_a_failed_calculation_is_visible_not_silent(conn, profile):
    """docs/old/DESIGN.md section 23: an empty transit list and a broken ephemeris
    must never look the same."""

    class BrokenEngine(FixtureAstrologyEngine):
        def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
            raise RuntimeError("ephemeris unavailable")

    async with app_with(conn, BrokenEngine()).run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        sky, _ = bodies(pilot)

        assert "Sky calculation failed" in sky
        assert "ephemeris unavailable" in sky


async def test_an_empty_ranking_reads_as_a_quiet_sky(conn, profile):
    """No transit close enough is a real answer, and a different one from
    a failure."""

    class QuietEngine(FixtureAstrologyEngine):
        def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
            snapshot = super().calculate_transits(natal, instant)
            return snapshot.model_copy(update={"raw_aspects": []})

    async with app_with(conn, QuietEngine()).run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        _, transits = bodies(pilot)

        assert "0 significant transits" in transits
        assert "Nothing is close enough" in transits


# -- the invariant ----------------------------------------------------------


async def test_it_never_reaches_for_a_current_location(conn, profile):
    """docs/old/DESIGN.md section 3.2: only the natal chart uses a place. The engine
    is asked for transits against the saved chart at an instant and nothing
    else, and no current house, Ascendant or Midheaven is displayed.
    """
    calls: list[tuple[NatalChart, datetime]] = []
    natal_calls: list[BirthData] = []

    class RecordingEngine(FixtureAstrologyEngine):
        def calculate_natal(self, birth: BirthData) -> NatalChart:
            natal_calls.append(birth)
            return super().calculate_natal(birth)

        def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
            calls.append((natal, instant))
            return super().calculate_transits(natal, instant)

    async with app_with(conn, RecordingEngine()).run_test() as pilot:
        await settle(pilot)
        await open_cosmos(pilot)
        sky, transits = bodies(pilot)

    # Opening the screen recalculated no chart, and every transit call was
    # the saved chart plus an instant - there is no third argument a
    # current location could arrive in.
    assert natal_calls == []
    assert calls and all(natal == profile.natal_chart for natal, _ in calls)

    rendered = f"{sky}\n{transits}".lower()
    assert "house" not in rendered
    # The birthplace belongs to the chart screen, not to the sky.
    assert profile.birth_data.place_label not in f"{sky}\n{transits}"
    assert str(profile.birth_data.latitude) not in rendered


# -- layout -----------------------------------------------------------------


@pytest.mark.parametrize("size", [(200, 55), (120, 40)])
async def test_the_two_lists_sit_side_by_side_when_wide(app: SyzygyApp, profile, size):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await open_cosmos(pilot)

        sky = q(pilot, "#cosmos-sky").region
        transits = q(pilot, "#cosmos-transits").region
        assert transits.x >= sky.right
        assert transits.height == sky.height


@pytest.mark.parametrize("size", [(80, 24), (100, 32)])
async def test_the_two_lists_stack_when_narrow(app: SyzygyApp, profile, size):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await open_cosmos(pilot)

        sky = q(pilot, "#cosmos-sky").region
        transits = q(pilot, "#cosmos-transits").region
        assert transits.y >= sky.bottom
        assert transits.x == sky.x
