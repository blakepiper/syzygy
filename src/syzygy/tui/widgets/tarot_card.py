"""The drawn card, as the screen's focal object (docs/old/DESIGN.md section 18.2).

The card is reference data by the time it reaches this widget - it renders
`syzygy.domain.tarot.TarotCard` exactly as the deck file defines it and
invents no correspondence of its own.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.text import Text
from textual.widgets import Static

from syzygy.domain.tarot import TarotCard
from syzygy.tui import palette
from syzygy.tui.widgets.card_art import art_size_for, render_card_pixels
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs

INNER_WIDTH = 27

#: Fallback art box for the rare case where the widget is asked to render
#: before it has been laid out and has no size yet. Portrait, and in image
#: pixels - see `card_art`'s module docstring on why the height is not
#: halved here.
DEFAULT_ART_COLUMNS = 22


def correspondence_label(card: TarotCard, glyphs: GlyphSet | None = None) -> str:
    """The card's astrological attribution in one line, from the deck data.

    Princess cards have no zodiacal attribution at all (the source text
    says so explicitly - docs/THOTH_INGESTION_MAP.md section 11), and this
    says so rather than inventing one.
    """
    marks = glyphs or default_glyphs()
    astrology = card.astrology
    if astrology is None:
        if card.element is not None:
            return f"{marks.element(card.element.value)} {card.element.value.upper()}"
        return "NO ZODIACAL ATTRIBUTION"

    if astrology.type == "element" and card.element is not None:
        return f"{marks.element(card.element.value)} {card.element.value.upper()}"
    if astrology.type == "planet" and astrology.planet is not None:
        return f"{marks.body(astrology.planet)} {astrology.planet.upper()}"
    if astrology.type == "sign" and astrology.sign is not None:
        return f"{marks.sign(astrology.sign)} {astrology.sign.upper()}"
    if astrology.type == "decan" and astrology.planet is not None and astrology.decan is not None:
        decan = astrology.decan
        return (
            f"{marks.body(astrology.planet)} {astrology.planet.upper()} in "
            f"{marks.sign(decan.sign)} {decan.sign.upper()} "
            f"{decan.start_degree}°-{decan.end_degree}°"
        )
    if astrology.type == "court_decan_span" and astrology.court_span is not None:
        span = astrology.court_span
        return (
            f"{marks.sign(span.start_sign)} {span.start_sign.upper()} {span.start_degree}° - "
            f"{marks.sign(span.end_sign)} {span.end_sign.upper()} {span.end_degree}°"
        )
    return "NO ZODIACAL ATTRIBUTION"


class TarotCardWidget(Static):
    """The card face, or its back while the draw is still concealed."""

    def __init__(
        self,
        card: TarotCard | None = None,
        *,
        glyphs: GlyphSet | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._glyphs = glyphs or default_glyphs()
        self._card = card
        # Content is rendered on mount, not here: it is sized from the
        # widget's own cell box, and `self.size` is not available until
        # `Widget.__init__` has run and the widget has been laid out.
        super().__init__("", id=id, classes=classes)

    @property
    def card(self) -> TarotCard | None:
        return self._card

    def on_mount(self) -> None:
        self.update(self._content())

    def set_card(self, card: TarotCard | None) -> None:
        """Turn the card face up (or, with `None`, face down again)."""
        self._card = card
        self.update(self._content())

    def on_resize(self) -> None:
        """Re-render the art at the new size. The illustration is sized
        from the widget's actual box, so it has to be rebuilt when that
        box changes - otherwise it keeps whatever size it happened to be
        laid out at first."""
        if self._card is not None:
            self.update(self._content())

    def _text_lines(self, card: TarotCard) -> list[tuple[str, str]]:
        """The card's own words, as (line, style) pairs."""
        lines = [
            (card.roman_numeral or "", palette.LUNAR),
            ("", ""),
            (card.display_name.upper(), f"bold {palette.BONE}"),
        ]
        if card.full_name != card.display_name:
            lines.append((card.full_name, palette.MUTED))
        lines.append(("", ""))
        lines.append((correspondence_label(card, self._glyphs), palette.ACCENT))
        return lines

    def _art_box(self, text_rows: int) -> tuple[int, int]:
        """(columns, cell rows) left for the illustration once `text_rows`
        and the blank row between art and text are reserved."""
        size = self.size
        if not size.width or not size.height:
            # Not laid out yet (constructed in `compose`, rendered before
            # the first resize): fall back to the nominal portrait box.
            return DEFAULT_ART_COLUMNS, DEFAULT_ART_COLUMNS
        return size.width, max(0, size.height - text_rows - 1)

    def _content(self) -> RenderableType:
        if self._card is None:
            back = Text()
            for index in range(5):
                back.append("╱" * INNER_WIDTH + ("\n" if index < 4 else ""), style=palette.DIM)
            return back

        card = self._card
        lines = self._text_lines(card)
        text = Text("\n".join(line for line, _ in lines))
        offset = 0
        for line, style in lines:
            if style:
                text.stylize(style, offset, offset + len(line))
            offset += len(line) + 1

        # Measured, not assumed: a long correspondence label ("MERCURY in
        # VIRGO 20°-30°") wraps at these widths, and reserving a fixed
        # row count let the art push the card's own words out of the box.
        width = self.size.width or DEFAULT_ART_COLUMNS
        text_rows = sum(max(1, -(-cell_len(line) // width)) for line, _ in lines)

        size = art_size_for(card.id, *self._art_box(text_rows))
        if size is None:
            # Too small for legible art, or no art mapped for this id. The
            # card's words carry it either way - never a blank box
            # (M11.5c).
            return text
        pixels = render_card_pixels(card.id, size)
        if pixels is None:  # defensive - every card in the deck has art
            return text
        return Group(pixels, Text(""), text)
