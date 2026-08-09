"""Layout at the breakpoints (M12.5).

The complaint these tests pin down was "the display feels largely empty",
and its two halves are easy to regress in opposite directions: a screen
can stop using the space it has, or it can use space it does not have and
push its own content off the bottom. Both were real here - the reveal's
card overflowed 100x32 and 120x40 while leaving a 55-row terminal
two-thirds empty, and the reading screen gave the interpretation two rows
to scroll in at the ideal size.

So each screen is checked at the tier sizes for both: nothing that matters
is off-screen, and the parts that should grow did. These are assertions
about geometry, not about appearance - a snapshot of cells would fail on
every wording change and tell nobody anything.
"""

from __future__ import annotations

import pytest
from textual.geometry import Region
from textual.widget import Widget

from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.base import IDEAL_HEIGHT, IDEAL_WIDTH, TALL_HEIGHT, WIDE_WIDTH
from syzygy.tui.screens.chart import ChartScreen
from syzygy.tui.screens.consultation_result import ConsultationResultScreen
from syzygy.tui.screens.oracle_ask import OracleAskScreen
from syzygy.tui.screens.reveal import RevealScreen
from syzygy.tui.screens.too_small import MIN_HEIGHT, MIN_WIDTH

from .test_ritual_flow import settle

#: One size per tier, plus the two that were actually broken.
FLOOR = (MIN_WIDTH, MIN_HEIGHT)
IDEAL = (IDEAL_WIDTH, IDEAL_HEIGHT)
WIDE = (WIDE_WIDTH, 40)
TALL = (WIDE_WIDTH, TALL_HEIGHT)
FULLSCREEN = (200, 55)
EVERY_TIER = [FLOOR, IDEAL, WIDE, TALL, FULLSCREEN]


def on_screen(widget: Widget) -> bool:
    """Is `widget` wholly inside its screen, rather than hanging off an
    edge where the terminal will simply not draw it?"""
    screen = widget.screen
    return screen.region.contains_region(widget.region)


def region_of(pilot, selector: str) -> Region:
    return pilot.app.screen.query_one(selector).region


async def reach_reveal(pilot) -> None:
    await pilot.press("enter")
    await pilot.pause()
    for _ in range(3):
        await pilot.press("space")
    await pilot.press("enter")
    await settle(pilot)
    assert isinstance(pilot.app.screen, RevealScreen)


async def reach_oracle_result(pilot) -> None:
    await pilot.press("o")
    await settle(pilot)
    assert isinstance(pilot.app.screen, OracleAskScreen)
    pilot.app.screen.query_one("#oracle-question").value = "What needs attention?"
    await pilot.press("enter")
    await settle(pilot)
    for _ in range(3):
        await pilot.press("space")
    await pilot.press("enter")
    await settle(pilot, 6)
    assert isinstance(pilot.app.screen, ConsultationResultScreen)


# -- the tiers themselves ---------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (FLOOR, {"-compact"}),
        ((IDEAL_WIDTH - 1, IDEAL_HEIGHT), {"-compact"}),
        ((IDEAL_WIDTH, IDEAL_HEIGHT - 1), {"-compact"}),
        (IDEAL, set()),
        ((WIDE_WIDTH - 1, IDEAL_HEIGHT), set()),
        (WIDE, {"-wide"}),
        ((IDEAL_WIDTH, TALL_HEIGHT), {"-tall"}),
        (TALL, {"-wide", "-tall"}),
        (FULLSCREEN, {"-wide", "-tall"}),
    ],
)
async def test_the_tier_classes_follow_the_thresholds(app: SyzygyApp, profile, size, expected):
    """`-compact`, `-wide` and `-tall` are independent, and every screen
    gets them from `SyzygyScreen` rather than measuring itself."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        classes = pilot.app.screen.classes & {"-compact", "-wide", "-tall"}
        assert classes == expected


# -- home -------------------------------------------------------------------


@pytest.mark.parametrize("size", EVERY_TIER)
async def test_the_wheel_is_reachable_at_every_supported_size(app: SyzygyApp, profile, size):
    """The primary action is the one thing on the home screen that must
    never be off the bottom edge - at the floor it was, once the three
    regions gained headings."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        assert on_screen(pilot.app.screen.query_one("#primary-action"))


@pytest.mark.parametrize("size", [WIDE, TALL, FULLSCREEN])
async def test_home_is_three_columns_when_wide(app: SyzygyApp, profile, size):
    """SELF, COSMOS and CHANCE side by side, in the axis's own order, each
    taking a real share of the width and the full height."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        columns = [region_of(pilot, f"#home-{name}") for name in ("self", "cosmos", "chance")]

        assert [column.x for column in columns] == sorted(column.x for column in columns)
        assert all(column.x != columns[0].x for column in columns[1:])
        assert all(column.width >= 30 for column in columns)
        # Full height, so the rules between them structure the whole
        # screen rather than stopping under the shortest column.
        assert all(column.bottom > size[1] * 0.6 for column in columns)


@pytest.mark.parametrize("size", [FLOOR, IDEAL])
async def test_home_stacks_below_the_wide_threshold(app: SyzygyApp, profile, size):
    """The same three regions, in one column, all still on screen."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        columns = [region_of(pilot, f"#home-{name}") for name in ("self", "cosmos", "chance")]

        assert len({column.x for column in columns}) == 1
        assert [column.y for column in columns] == sorted(column.y for column in columns)
        # Stacked, the regions are named by their own headings - the
        # alignment axis above no longer points at them.
        headings = pilot.app.screen.query(".column-heading")
        assert len(headings) == 3
        assert all(heading.display and heading.region.height for heading in headings)


async def test_the_anchors_fit_the_narrowest_terminal(app: SyzygyApp, profile):
    """Sun, Moon and Ascendant on three rows, not one. Side by side they
    ran to about 100 cells and the Ascendant fell off the right edge at
    the 80-column floor."""
    async with app.run_test(size=FLOOR) as pilot:
        await settle(pilot)
        anchors = [region_of(pilot, f"#anchor-{name}") for name in ("sun", "moon", "asc")]

        assert len({anchor.y for anchor in anchors}) == 3
        assert all(anchor.right <= MIN_WIDTH for anchor in anchors)


# -- oracle -----------------------------------------------------------------


@pytest.mark.parametrize("size", EVERY_TIER)
async def test_oracle_question_and_result_keep_essential_controls_visible(
    app: SyzygyApp, profile, size
):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await pilot.press("o")
        await settle(pilot)
        for selector in ("#oracle-question", "#oracle-submit"):
            assert on_screen(pilot.app.screen.query_one(selector)), selector

        await reach_oracle_result(pilot)
        # Both chance objects and the interpretation stay on screen at
        # every tier: the card, the hexagram and its lines, the movement
        # note, the panel, and the keys.
        for selector in (
            "#consultation-card",
            "#consultation-hexagram",
            "#consultation-lines",
            "#consultation-movement",
            "#consultation-panel",
            "#consultation-keys",
        ):
            assert on_screen(pilot.app.screen.query_one(selector)), selector
        assert region_of(pilot, "#consultation-panel").height >= 6
        assert len(pilot.app.screen.query(".cast-line")) == 6


# -- reading ----------------------------------------------------------------


@pytest.mark.parametrize("size", EVERY_TIER)
async def test_the_interpretation_gets_room_to_be_read(app: SyzygyApp, profile, size):
    """The regression that motivated M12.5c: stacked under a 24-row card,
    the reading panel was left about two rows at the ideal size. It is the
    payload of the screen and gets the slack now."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await reach_reveal(pilot)
        await pilot.press("enter")
        await settle(pilot, 8)

        panel = region_of(pilot, "#reading-panel")
        assert panel.height >= 6
        if size != FLOOR:
            # Above the floor it is the largest thing on the screen.
            assert panel.height >= region_of(pilot, "#reading-card").height


@pytest.mark.parametrize("size", [IDEAL, WIDE, FULLSCREEN])
async def test_the_reading_is_two_columns_above_the_floor(app: SyzygyApp, profile, size):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await reach_reveal(pilot)
        await pilot.press("enter")
        await settle(pilot, 8)

        aside = region_of(pilot, "#reading-aside")
        main = region_of(pilot, "#reading-main")
        assert main.x >= aside.right
        # The card keeps its own width whatever the terminal does; the
        # reading takes everything else.
        assert main.width > aside.width


async def test_prose_keeps_a_readable_measure_on_a_huge_terminal(app: SyzygyApp, profile):
    """Unbounded, a paragraph ran the full 200 columns as one line."""
    async with app.run_test(size=FULLSCREEN) as pilot:
        await settle(pilot)
        await reach_reveal(pilot)
        await pilot.press("enter")
        await settle(pilot, 8)

        assert region_of(pilot, "#reading-body").width <= 88


# -- reveal -----------------------------------------------------------------


@pytest.mark.parametrize("size", EVERY_TIER)
async def test_the_reveal_fits_and_fills(app: SyzygyApp, profile, size):
    """The card takes the slack between a floor and a ceiling, so it can
    neither push the caption and the key hint off the bottom nor sit at a
    third of the height of a tall terminal."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await reach_reveal(pilot)

        for selector in ("#reveal-card", "#reveal-caption", "#reveal-hint"):
            assert on_screen(pilot.app.screen.query_one(selector)), selector

        card = region_of(pilot, "#reveal-card")
        body = region_of(pilot, "#reveal-body")
        assert card.height >= body.height * 0.5


async def test_the_reveal_card_grows_with_the_rows_available(app: SyzygyApp, profile):
    async with app.run_test(size=IDEAL) as pilot:
        await settle(pilot)
        await reach_reveal(pilot)
        at_ideal = region_of(pilot, "#reveal-card")

        await pilot.resize_terminal(*FULLSCREEN)
        await settle(pilot)
        when_tall = region_of(pilot, "#reveal-card")

    assert when_tall.height > at_ideal.height
    assert when_tall.width > at_ideal.width


# -- chart ------------------------------------------------------------------


async def test_the_chart_puts_aspects_beside_placements_when_wide(app: SyzygyApp, profile):
    """Stacked in one scroller, the aspects sat below the fold on a screen
    that was three-quarters empty."""
    async with app.run_test(size=FULLSCREEN) as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ChartScreen)

        placements = region_of(pilot, "#chart-placements")
        aspects = region_of(pilot, "#chart-aspects")
        assert aspects.x >= placements.right
        assert aspects.height == placements.height


async def test_the_chart_stacks_into_one_scroller_when_narrow(app: SyzygyApp, profile):
    """Two independent scrollbars in one narrow column would be worse than
    the single list they replace."""
    async with app.run_test(size=IDEAL) as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)

        placements = region_of(pilot, "#chart-placements")
        aspects = region_of(pilot, "#chart-aspects")
        assert aspects.y >= placements.bottom
        assert aspects.x == placements.x
