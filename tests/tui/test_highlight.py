"""The highlighted row is unmistakable (M17.4).

The defect: `ListItem.--highlight` set `$syz-panel` over a row of
`$syz-field` - two near-blacks a cell apart in luminance. On the profile
list, "which self am I about to open" was invisible.

These assert *relationships*, not hex pairs. A rule that named colours
directly would pass just as happily if a future palette change made
`$syz-accent` another dark grey, which is precisely the regression worth
preventing: the highlight has to remain a reversal of the ordinary row,
and it has to survive a terminal that renders no colour at all.
"""

from __future__ import annotations

import re
from importlib import resources

import pytest
from textual.widgets import ListView

from syzygy.tui import palette
from syzygy.tui.app import SyzygyApp
from syzygy.tui.widgets.marked_list import HIGHLIGHT_MARKER, MarkedListItem

from .test_ritual_flow import settle, turn_the_wheel

_STYLESHEET = resources.files("syzygy.tui").joinpath("syzygy.tcss").read_text()


def rule(selector: str) -> dict[str, str]:
    """The declarations of the last block matching `selector` exactly."""
    pattern = re.compile(
        rf"(?:^|\n)\s*{re.escape(selector)}\s*\{{(.*?)\}}", re.DOTALL
    )
    blocks = pattern.findall(_STYLESHEET)
    assert blocks, f"no rule for {selector!r} in syzygy.tcss"
    declarations: dict[str, str] = {}
    for line in blocks[-1].splitlines():
        line = re.sub(r"/\*.*?\*/", "", line).strip().rstrip(";")
        if ":" in line:
            name, _, value = line.partition(":")
            declarations[name.strip()] = value.strip()
    return declarations


def channels(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def relative_luminance(colour: str) -> float:
    """WCAG relative luminance, so contrast can be stated as a ratio."""

    def linear(value: int) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)))[::-1]
    return (lighter + 0.05) / (darker + 0.05)


def named(value: str) -> str:
    """Resolve a `$syz-*` reference to its palette constant."""
    assert value.startswith("$"), f"{value!r} is a literal; name it in the palette instead"
    return palette.TCSS_EQUIVALENTS[value[1:]]


# -- the rule itself --------------------------------------------------------


def test_the_highlight_inverts_the_ordinary_row_rather_than_tinting_it():
    ordinary = rule("ListItem")
    highlighted = rule("ListItem.--highlight")

    assert named(highlighted["background"]) == named(ordinary["color"]) or contrast(
        named(highlighted["background"]), named(ordinary["background"])
    ) >= 7.0
    # Foreground and background swap roles: what was the row's paper is
    # now its ink.
    assert relative_luminance(named(highlighted["background"])) > relative_luminance(
        named(ordinary["background"])
    )
    assert relative_luminance(named(highlighted["color"])) < relative_luminance(
        named(ordinary["color"])
    )


def test_the_highlight_is_high_contrast_against_both_the_row_and_its_own_text():
    ordinary = rule("ListItem")
    highlighted = rule("ListItem.--highlight")

    # Legible: the row's own text against the row's own background.
    assert contrast(named(highlighted["background"]), named(highlighted["color"])) >= 7.0
    # Findable: the highlighted row against its unhighlighted neighbours.
    assert contrast(named(highlighted["background"]), named(ordinary["background"])) >= 7.0


def test_the_old_two_greys_highlight_would_fail_this():
    """Documents the defect: `$syz-panel` on `$syz-field` is a contrast
    ratio of about 1.1 - indistinguishable at a glance."""
    assert contrast(palette.PANEL, palette.FIELD) < 1.5


def test_the_highlight_does_not_lean_on_colour_alone():
    highlighted = rule("ListItem.--highlight")
    assert "bold" in highlighted.get("text-style", "")


def test_a_focused_button_gets_the_same_treatment_as_a_highlighted_row():
    """One answer to "where am I", everywhere (M17.4b)."""
    focused = rule("Button:focus")
    highlighted = rule("ListItem.--highlight")
    assert focused["background"] == highlighted["background"]
    assert focused["color"] == highlighted["color"]


# -- the marker glyph -------------------------------------------------------


async def test_the_profile_list_marks_the_highlighted_row(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)

        items = list(pilot.app.screen.query(MarkedListItem))
        assert items, "the profile list should have rows"
        marked = [
            item
            for item in items
            if HIGHLIGHT_MARKER in item.query_one("Label").visual.plain
        ]
        assert len(marked) == 1
        assert marked[0] is pilot.app.screen.query_one("#profile-list", ListView).highlighted_child


async def test_the_marker_moves_with_the_highlight(services, conn, profile):
    """Two profiles, so there is somewhere for the marker to move to."""
    import uuid

    from syzygy.storage.profiles import insert_profile

    from .conftest import FIXED_NOW

    second = profile.model_copy(
        update={"id": str(uuid.uuid4()), "display_name": "Other", "created_at_utc": FIXED_NOW}
    )
    insert_profile(conn, second)

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        listing = pilot.app.screen.query_one("#profile-list", ListView)
        first_marked = listing.highlighted_child

        await pilot.press("down")
        await pilot.pause()

        moved = listing.highlighted_child
        assert moved is not first_marked
        assert HIGHLIGHT_MARKER in moved.query_one("Label").visual.plain
        assert HIGHLIGHT_MARKER not in first_marked.query_one("Label").visual.plain


async def test_the_marker_never_reflows_the_rows_words(app: SyzygyApp, profile):
    """Marked and unmarked rows are the same width, so moving the
    highlight does not shift a whole list sideways."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)

        item = pilot.app.screen.query_one(MarkedListItem)
        item.set_marked(True)
        marked = item.query_one("Label").visual.plain
        item.set_marked(False)
        unmarked = item.query_one("Label").visual.plain

        assert len(marked) == len(unmarked)
        assert item.label_text in marked
        assert item.label_text in unmarked


@pytest.mark.parametrize("screen_key", ["a", "p"])
async def test_every_list_screen_uses_marked_rows(services, profile, screen_key):
    """`archive` and `profile_select` both, so a future list cannot quietly
    go back to a bare `ListItem` (M17.4b)."""
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await pilot.press("escape")
        await settle(pilot)

        await pilot.press(screen_key)
        await settle(pilot)

        listing = pilot.app.screen.query_one(ListView)
        assert list(listing.children), "the list should not be empty in this test"
        assert all(isinstance(child, MarkedListItem) for child in listing.children)
