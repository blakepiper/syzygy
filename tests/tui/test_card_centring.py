"""The card sits centred inside its frame (M17.6).

The defect these pin down: `TarotCardWidget` returns a composite Rich
`Group`, and the widget's `content-align: center middle` does not reach
inside one. The half-block art renders at whatever width `art_size_for`
chose - quantised to even columns and capped at `MAX_COLUMNS` - so it was
almost always narrower than the frame and sat hard against the left edge,
under a caption that *was* centred and therefore made the misalignment
obvious.

The assertion is symmetry, not a column number: what matters is that the
art has the same amount of blank on both sides, at any width, including
the widths where the art is declined altogether and the card's own words
have to carry it.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from syzygy.sortes.deck import get_card
from syzygy.tui.app import SyzygyApp
from syzygy.tui.widgets.card_art import art_size_for
from syzygy.tui.widgets.tarot_card import TarotCardWidget

#: Half-block cells the art is drawn with. A row containing any of these
#: is an art row; the caption rows contain none of them.
_ART_CELLS = frozenset("▀▄█")


def render(renderable, width: int) -> list[str]:
    console = Console(file=io.StringIO(), width=200, legacy_windows=False)
    lines = console.render_lines(renderable, console.options.update(width=width))
    return ["".join(segment.text for segment in line) for line in lines]


def padding_of(line: str) -> tuple[int, int]:
    """`(leading, trailing)` blank cells around the drawn part of `line`."""
    stripped = line.rstrip()
    return len(stripped) - len(stripped.lstrip()), len(line) - len(stripped)


def art_rows(lines: list[str]) -> list[str]:
    return [line for line in lines if _ART_CELLS & set(line)]


def text_rows(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip() and not _ART_CELLS & set(line)]


async def card_widget(app: SyzygyApp, pilot, width: int, height: int) -> TarotCardWidget:
    from textual.screen import Screen

    class _CardScreen(Screen):
        def compose(self):
            widget = TarotCardWidget(get_card("the_fool"), id="reveal-card")
            widget.styles.width = width
            widget.styles.height = height
            yield widget

    app.push_screen(_CardScreen())
    await pilot.pause()
    return app.screen.query_one(TarotCardWidget)


@pytest.mark.parametrize("width", [27, 30, 33, 41, 48])
async def test_the_art_has_equal_blank_on_both_sides(services, width):
    app = SyzygyApp(services)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        widget = await card_widget(app, pilot, width, 30)
        inner = widget.content_region.width
        lines = render(widget._content(), inner)

        rows = art_rows(lines)
        assert rows, f"no art rendered at width {width}"
        for line in rows:
            leading, trailing = padding_of(line)
            assert abs(leading - trailing) <= 1, (
                f"width {width}: art off-centre by {leading - trailing} cells"
            )


@pytest.mark.parametrize("width", [27, 33, 41])
async def test_the_cards_words_stay_centred(services, width):
    app = SyzygyApp(services)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        widget = await card_widget(app, pilot, width, 30)
        inner = widget.content_region.width
        lines = render(widget._content(), inner)

        captions = text_rows(lines)
        assert any("THE FOOL" in line for line in captions)
        for line in captions:
            leading, trailing = padding_of(line)
            assert abs(leading - trailing) <= 1, f"width {width}: {line!r} off-centre"


async def test_the_text_only_fallback_is_still_centred_and_still_the_words(services):
    """Below the legibility floor there is no art, and `art_size_for`'s
    `None` must keep meaning "the words carry it" (M11.5c)."""
    app = SyzygyApp(services)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        widget = await card_widget(app, pilot, 33, 9)
        inner = widget.content_region.width
        assert art_size_for("the_fool", *widget._art_box(6)) is None

        lines = render(widget._content(), inner)
        assert not art_rows(lines)
        assert any("THE FOOL" in line for line in lines)
        for line in text_rows(lines):
            leading, trailing = padding_of(line)
            assert abs(leading - trailing) <= 1


async def test_the_face_down_card_back_is_centred(services):
    app = SyzygyApp(services)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()

        from textual.screen import Screen

        class _BackScreen(Screen):
            def compose(self):
                widget = TarotCardWidget(id="reveal-card")
                widget.styles.width = 41
                widget.styles.height = 30
                yield widget

        app.push_screen(_BackScreen())
        await pilot.pause()
        widget = app.screen.query_one(TarotCardWidget)
        for line in render(widget._content(), widget.content_region.width):
            if line.strip():
                leading, trailing = padding_of(line)
                assert abs(leading - trailing) <= 1


async def test_the_logo_is_centred_in_its_box(services):
    """The same defect at the other art site (M17.6b).

    Measured against the image's *own* margins rather than against bare
    ink: the wordmark PNG is keyed to transparency and its glyphs are not
    symmetric inside their bounding box, so the honest question is whether
    the widget adds the same number of cells on each side of the image -
    not whether the ink happens to land in the middle.
    """
    from textual.screen import Screen

    from syzygy.tui.widgets import pixel_art
    from syzygy.tui.widgets.brand import LOGO_PATH, MAX_LOGO_COLUMNS, Logo

    app = SyzygyApp(services)

    class _LogoScreen(Screen):
        def compose(self):
            logo = Logo(id="startup-logo")
            logo.styles.width = 72
            logo.styles.height = 8
            yield logo

    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        app.push_screen(_LogoScreen())
        await pilot.pause()
        logo = app.screen.query_one(Logo)
        box = logo.content_region
        fitted = pixel_art.fit_size(
            LOGO_PATH, box.width, box.height, max_columns=MAX_LOGO_COLUMNS
        )
        assert fitted is not None
        assert box.width > fitted[0], "the box has to be wider than the art to test centring"

        intrinsic = render(pixel_art.render_pixels(LOGO_PATH, fitted), fitted[0])
        placed = render(logo._content(), box.width)
        assert len(placed) == len(intrinsic)

        for own, drawn in zip(intrinsic, placed, strict=True):
            if not own.strip():
                continue
            own_leading, own_trailing = padding_of(own)
            leading, trailing = padding_of(drawn)
            assert abs((leading - own_leading) - (trailing - own_trailing)) <= 1


async def test_undecodable_brand_art_degrades_to_nothing(services, monkeypatch):
    """M17.3c/M17.6b: decoration never becomes a traceback."""
    from textual.screen import Screen

    from syzygy.tui.widgets import pixel_art
    from syzygy.tui.widgets.brand import Mascot

    def explode(*_args, **_kwargs):
        raise ValueError("truncated PNG")

    monkeypatch.setattr(pixel_art, "render_pixels", explode)
    app = SyzygyApp(services)

    class _MascotScreen(Screen):
        def compose(self):
            mascot = Mascot(id="startup-mascot")
            mascot.styles.width = 22
            mascot.styles.height = 16
            yield mascot

    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        app.push_screen(_MascotScreen())
        await pilot.pause()
        mascot = app.screen.query_one(Mascot)
        rendered = render(mascot._content(), mascot.content_region.width)
        assert not any(line.strip() for line in rendered)
