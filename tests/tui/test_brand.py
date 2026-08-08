"""The bundled logo and mascot (M12.2).

Brand assets are decoration: a screen must never fail to render because
one is missing or the box is too small. These tests check that they are
actually bundled and actually render, and that every failure path
degrades to text rather than raising.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich_pixels import Pixels

from syzygy.tui.widgets import pixel_art
from syzygy.tui.widgets.brand import (
    ASCII_WORDMARK,
    LOGO_PATH,
    MASCOT_PATH,
    MAX_LOGO_COLUMNS,
    BrandImage,
    Logo,
    Mascot,
)


@pytest.mark.parametrize("relative_path", [LOGO_PATH, MASCOT_PATH])
def test_the_asset_is_bundled_and_readable_as_a_resource(relative_path):
    """Read through `importlib.resources`, not the filesystem - that is
    what has to work from a zipped wheel."""
    assert pixel_art.aspect_ratio(relative_path) is not None


def test_the_logo_is_a_wide_wordmark_and_the_mascot_is_portrait():
    assert pixel_art.aspect_ratio(LOGO_PATH) < 0.5
    assert pixel_art.aspect_ratio(MASCOT_PATH) > 1.0


@pytest.mark.parametrize(("columns", "cell_rows"), [(56, 8), (52, 6), (64, 10)])
def test_the_logo_renders_as_an_image_at_the_sizes_the_welcome_screen_uses(columns, cell_rows):
    size = pixel_art.fit_size(LOGO_PATH, columns, cell_rows, max_columns=MAX_LOGO_COLUMNS)
    assert size is not None
    assert isinstance(pixel_art.render_pixels(LOGO_PATH, size), Pixels)


@pytest.mark.parametrize(("columns", "cell_rows"), [(22, 16), (20, 14), (30, 24)])
def test_the_mascot_renders_as_an_image_at_the_sizes_the_welcome_screen_uses(columns, cell_rows):
    size = pixel_art.fit_size(MASCOT_PATH, columns, cell_rows)
    assert size is not None
    assert isinstance(pixel_art.render_pixels(MASCOT_PATH, size), Pixels)


def test_assets_keep_their_aspect_ratio():
    for relative_path, box in ((LOGO_PATH, (56, 8)), (MASCOT_PATH, (22, 16))):
        size = pixel_art.fit_size(relative_path, *box, max_columns=MAX_LOGO_COLUMNS)
        assert size is not None
        assert abs(size[1] / size[0] - pixel_art.aspect_ratio(relative_path)) < 0.12


def test_a_missing_asset_is_not_an_error():
    """Decoration must never be load-bearing."""
    assert pixel_art.aspect_ratio("brand/nope.png") is None
    assert pixel_art.fit_size("brand/nope.png", 40, 20) is None
    assert pixel_art.render_pixels("brand/nope.png", (20, 20)) is None


def _render(widget: BrandImage, width: int) -> str:
    console = Console(file=io.StringIO(), width=200, legacy_windows=False)
    lines = console.render_lines(widget._content(), console.options.update(width=width))
    return "\n".join("".join(segment.text for segment in line) for line in lines)


async def _mounted(app_factory, widget: BrandImage, *, width: int, height: int) -> str:
    from textual.containers import Center
    from textual.screen import Screen

    class _BrandScreen(Screen):
        def compose(self):
            with Center():
                yield widget

    app = app_factory()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(_BrandScreen())
        await pilot.pause()
        widget.styles.width = width
        widget.styles.height = height
        await pilot.pause()
        return _render(widget, widget.size.width)


async def test_the_logo_falls_back_to_the_ascii_wordmark_when_squeezed(services):
    from syzygy.tui.app import SyzygyApp

    rendered = await _mounted(lambda: SyzygyApp(services), Logo(), width=12, height=3)
    assert "███" in rendered


async def test_the_mascot_falls_back_to_nothing_rather_than_a_smear(services):
    """It has no text form, so too-small means absent - never a squashed
    illustration in place of the copy beside it."""
    from syzygy.tui.app import SyzygyApp

    rendered = await _mounted(lambda: SyzygyApp(services), Mascot(), width=8, height=3)
    assert rendered.strip() == ""


async def test_the_welcome_screen_shows_both_assets_at_a_roomy_size(services):
    from syzygy.tui.app import SyzygyApp
    from syzygy.tui.screens.welcome import WelcomeScreen

    app = SyzygyApp(services)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, WelcomeScreen)
        logo = app.screen.query_one("#welcome-logo", Logo)
        mascot = app.screen.query_one("#welcome-mascot", Mascot)
        assert logo.size.width > 0 and logo.size.height > 0
        assert mascot.size.width > 0 and mascot.size.height > 0

        # And the copy beside the mascot still has room to be read - an
        # auto-width body inside an auto-width Horizontal collapses to a
        # few columns, which is invisible rather than merely cramped.
        body = app.screen.query_one("#welcome-body")
        assert body.size.width >= 40


async def test_the_welcome_screen_drops_the_mascot_at_the_compact_floor(services):
    """22 columns are worth more to the copy at 80x24."""
    from syzygy.tui.app import SyzygyApp

    app = SyzygyApp(services)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        mascot = app.screen.query_one("#welcome-mascot", Mascot)
        assert mascot.size.width == 0
        assert app.screen.query_one("#welcome-body").size.width >= 40


def test_the_ascii_wordmark_is_still_available_for_one_line_contexts():
    """A title bar has one row; pixel art needs several."""
    assert "SYZYGY" not in ASCII_WORDMARK  # it is drawn, not spelled
    assert ASCII_WORDMARK.count("\n") >= 5
