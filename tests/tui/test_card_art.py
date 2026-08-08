"""Card-art sizing (M11.5).

The reported defect was that the art "does not display correctly". The
cause was arithmetic, not plumbing: `resize` is in *image pixels* and the
half-cell renderer packs two image rows into every cell row, so the fixed
`(22, 17)` produced 22 columns by 9 rows - the illustration squashed to
about half its proper height. These tests pin the ratio rather than any
particular size, so a future layout change can make the card bigger or
smaller without silently distorting it again.
"""

from __future__ import annotations

import io
import math

import pytest
from rich.console import Console

from syzygy.sortes.deck import get_card, load_deck
from syzygy.tui.widgets import pixel_art
from syzygy.tui.widgets.card_art import (
    art_size_for,
    card_aspect_ratio,
    render_card_pixels,
)
from syzygy.tui.widgets.pixel_art import MAX_COLUMNS, MIN_CELL_ROWS, MIN_COLUMNS

#: Discrete cells cannot hit a real-valued ratio exactly; a card is
#: allowed to be off by a cell's worth of rounding, not by a factor of two.
ASPECT_TOLERANCE = 0.12


def cell_rows_for(size: tuple[int, int]) -> int:
    """Cell rows a `resize` of `size` actually occupies."""
    return math.ceil(size[1] / 2)


@pytest.mark.parametrize(
    ("columns", "cell_rows"),
    [(27, 18), (27, 14), (24, 16), (20, 12), (16, 10), (40, 30), (60, 40)],
)
def test_art_size_preserves_the_source_aspect_ratio(columns, cell_rows):
    for card in load_deck():
        size = art_size_for(card.id, columns, cell_rows)
        if size is None:
            continue
        width, height = size
        rendered_aspect = height / width
        source_aspect = card_aspect_ratio(card.id)
        assert abs(rendered_aspect - source_aspect) < ASPECT_TOLERANCE, (
            f"{card.id} at {columns}x{cell_rows}: {rendered_aspect:.3f} "
            f"vs source {source_aspect:.3f}"
        )


@pytest.mark.parametrize(
    ("columns", "cell_rows"),
    [(27, 18), (27, 14), (24, 16), (20, 12), (16, 10), (40, 30)],
)
def test_art_never_exceeds_the_box_it_was_given(columns, cell_rows):
    for card in load_deck():
        size = art_size_for(card.id, columns, cell_rows)
        if size is None:
            continue
        assert size[0] <= columns
        assert cell_rows_for(size) <= cell_rows


def test_art_is_declined_rather_than_squashed_when_the_box_is_too_short():
    """A wide but very short box must not produce a letterboxed smear."""
    assert art_size_for("the_fool", 40, 2) is None
    assert art_size_for("the_fool", 40, MIN_CELL_ROWS - 1) is None


def test_art_is_declined_when_the_box_is_too_narrow():
    assert art_size_for("the_fool", MIN_COLUMNS - 1, 40) is None


def test_art_is_capped_however_much_room_there_is():
    size = art_size_for("the_fool", 500, 500)
    assert size is not None
    assert size[0] <= MAX_COLUMNS


def test_unknown_card_ids_have_no_art_and_no_aspect():
    assert card_aspect_ratio("not_a_card") is None
    assert art_size_for("not_a_card", 30, 20) is None


def test_a_bigger_box_gives_bigger_art():
    small = art_size_for("the_fool", 16, 10)
    large = art_size_for("the_fool", 30, 24)
    assert small is not None and large is not None
    assert large[0] > small[0]
    assert large[1] > small[1]


def test_rendered_pixels_occupy_the_expected_cell_rows():
    """The bug in one assertion: `resize=(22, 17)` renders 9 rows, not 17.
    Whatever `art_size_for` returns, the renderer must actually produce
    the cell rows this module's arithmetic assumes."""
    size = art_size_for("the_fool", 27, 18)
    assert size is not None
    pixels = render_card_pixels("the_fool", size)
    assert pixels is not None

    console = Console(file=io.StringIO(), width=200, legacy_windows=False)
    lines = console.render_lines(pixels, console.options.update(width=size[0]))
    assert len(lines) == cell_rows_for(size)


def test_the_old_fixed_size_would_have_failed_this():
    """Documents the regression this file exists to prevent."""
    squashed = 17 / 22
    source = card_aspect_ratio("the_fool")
    assert abs(squashed - source) > ASPECT_TOLERANCE


def test_every_card_resolves_to_art_at_a_realistic_box():
    for card in load_deck():
        size = art_size_for(card.id, 27, 18)
        assert size is not None, card.id
        assert render_card_pixels(card.id, size) is not None, card.id


def test_render_is_cached_per_card_and_size():
    pixel_art.render_pixels.cache_clear()
    size = art_size_for("the_fool", 27, 18)
    render_card_pixels("the_fool", size)
    render_card_pixels("the_fool", size)
    assert pixel_art.render_pixels.cache_info().hits >= 1


def test_widths_are_quantised_so_a_resize_drag_cannot_flood_the_cache():
    """Every width between two steps must collapse onto the same size, or
    dragging a terminal edge decodes the PNG once per column crossed."""
    sizes = {art_size_for("the_fool", columns, 40) for columns in range(20, 32)}
    assert len(sizes) < 12
    assert all(size is not None and size[0] % 2 == 0 for size in sizes)


def test_the_card_widget_fits_its_box_for_every_card():
    """The art shares the widget with the card's own words, and a long
    correspondence label wraps. Reserving a fixed row count for the text
    let the illustration push those words out of the box."""
    import asyncio

    from textual.containers import Center, Vertical
    from textual.screen import Screen

    from syzygy.tui.widgets.tarot_card import TarotCardWidget

    from .conftest import FIXED_NOW, FixtureAstrologyEngine

    class _CardScreen(Screen):
        def compose(self):
            # Mirrors `RevealScreen`'s structure, not just its ids: the
            # card's height comes from `#reveal-stage` (M12.5c), so a bare
            # auto-height `Center` would give it a zero-row box and the
            # "does the content fit" question would have no box to ask
            # about.
            with Vertical(id="reveal-body"):
                with Center(id="reveal-stage"):
                    yield TarotCardWidget(id="reveal-card")

    async def check() -> list[tuple[str, int, int]]:
        from syzygy.clock import FixedClock
        from syzygy.interpretation.providers.fixture import FixtureProvider
        from syzygy.storage.database import connect
        from syzygy.storage.migrations import apply_all
        from syzygy.tui.app import SyzygyApp, SyzygyServices

        conn = connect(":memory:", check_same_thread=False)
        apply_all(conn)
        app = SyzygyApp(
            SyzygyServices(
                conn=conn,
                clock=FixedClock(FIXED_NOW),
                astrology=FixtureAstrologyEngine(),
                provider=FixtureProvider(),
            )
        )
        overflowing: list[tuple[str, int, int]] = []
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            app.push_screen(_CardScreen())
            await pilot.pause()
            widget = app.screen.query_one(TarotCardWidget)
            console = Console(file=io.StringIO(), width=200, legacy_windows=False)
            options = console.options.update(width=widget.size.width)
            for card in load_deck():
                widget.set_card(card)
                rows = len(console.render_lines(widget._content(), options))
                if rows > widget.size.height:
                    overflowing.append((card.id, rows, widget.size.height))
        conn.close()
        return overflowing

    assert asyncio.run(check()) == []


def test_a_short_card_widget_renders_the_text_card_instead_of_art():
    """M11.5c: too small for legible art means the words, never a blank
    box, a squashed smear, or a raised exception."""
    import asyncio

    from textual.containers import Center
    from textual.screen import Screen

    from syzygy.tui.widgets.tarot_card import TarotCardWidget

    from .conftest import FIXED_NOW, FixtureAstrologyEngine

    class _TinyCardScreen(Screen):
        def compose(self):
            with Center():
                yield TarotCardWidget(get_card("the_fool"), id="reveal-card")

    async def render() -> str:
        from syzygy.clock import FixedClock
        from syzygy.interpretation.providers.fixture import FixtureProvider
        from syzygy.storage.database import connect
        from syzygy.storage.migrations import apply_all
        from syzygy.tui.app import SyzygyApp, SyzygyServices

        conn = connect(":memory:", check_same_thread=False)
        apply_all(conn)
        app = SyzygyApp(
            SyzygyServices(
                conn=conn,
                clock=FixedClock(FIXED_NOW),
                astrology=FixtureAstrologyEngine(),
                provider=FixtureProvider(),
            )
        )
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            app.push_screen(_TinyCardScreen())
            await pilot.pause()
            widget = app.screen.query_one(TarotCardWidget)
            # Squeeze the box below the legibility floor. Set on the
            # widget rather than in CSS so the app stylesheet, which wins
            # over a screen's DEFAULT_CSS, cannot override it.
            widget.styles.height = 9
            await pilot.pause()
            assert art_size_for("the_fool", *widget._art_box(6)) is None
            console = Console(file=io.StringIO(), width=200, legacy_windows=False)
            lines = console.render_lines(
                widget._content(), console.options.update(width=widget.size.width)
            )
            conn.close()
            return "\n".join("".join(s.text for s in line) for line in lines)

    rendered = asyncio.run(render())
    assert "THE FOOL" in rendered
