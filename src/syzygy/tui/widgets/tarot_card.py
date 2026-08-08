"""The drawn card, as the screen's focal object (DESIGN.md section 18.2).

The card is reference data by the time it reaches this widget - it renders
`syzygy.domain.tarot.TarotCard` exactly as the deck file defines it and
invents no correspondence of its own.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from syzygy.domain.tarot import TarotCard
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs

INNER_WIDTH = 27


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
        super().__init__(self._content(), id=id, classes=classes)

    @property
    def card(self) -> TarotCard | None:
        return self._card

    def set_card(self, card: TarotCard | None) -> None:
        """Turn the card face up (or, with `None`, face down again)."""
        self._card = card
        self.update(self._content())

    def _content(self) -> Text:
        if self._card is None:
            back = Text()
            for index in range(5):
                back.append("╱" * INNER_WIDTH + ("\n" if index < 4 else ""), style="#4a4438")
            return back

        card = self._card
        text = Text()
        text.append(f"{card.roman_numeral or ''}\n", style="#7ea6c9")
        text.append("\n")
        text.append(f"{card.display_name.upper()}\n", style="bold #e6ddc9")
        if card.full_name != card.display_name:
            text.append(f"{card.full_name}\n", style="#8a8272")
        text.append("\n")
        text.append(correspondence_label(card, self._glyphs), style="#cf9b3f")
        return text
