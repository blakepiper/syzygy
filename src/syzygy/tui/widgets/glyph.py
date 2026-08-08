"""Glyph capability/fallback layer (DESIGN.md section 18.5).

Views must not hard-code Unicode astrological symbols: plenty of terminal
fonts have no planetary or zodiacal glyphs, and a reading that renders as
a row of tofu boxes is a failed reading. Every symbol the interface draws
goes through a `GlyphSet`, which resolves it to either the Unicode form or
an ASCII fallback.

`SYZYGY_ASCII=1` in the environment always forces the fallback set,
overriding detection - useful for a font that reports UTF-8 support but
still renders the occult glyphs as tofu. Absent that override,
`default_glyphs` inspects the output stream's encoding (falling back to
the process locale when the stream doesn't expose one, e.g. when stdout
is piped) - DESIGN.md section 18.5: "the UI must survive fonts that lack
specialized occult symbols."
"""

from __future__ import annotations

import locale
import os
import sys
from dataclasses import dataclass

from textual.widgets import Static

PLANET_GLYPHS: dict[str, str] = {
    "Sun": "☉",
    "Moon": "☽",
    "Mercury": "☿",
    "Venus": "♀",
    "Mars": "♂",
    "Jupiter": "♃",
    "Saturn": "♄",
    "Uranus": "♅",
    "Neptune": "♆",
    "Pluto": "♇",
    "Ascendant": "↑",
    "Midheaven": "↑",
}

PLANET_ASCII: dict[str, str] = {
    "Sun": "SU",
    "Moon": "MO",
    "Mercury": "ME",
    "Venus": "VE",
    "Mars": "MA",
    "Jupiter": "JU",
    "Saturn": "SA",
    "Uranus": "UR",
    "Neptune": "NE",
    "Pluto": "PL",
    "Ascendant": "AC",
    "Midheaven": "MC",
}

SIGN_GLYPHS: dict[str, str] = {
    "Aries": "♈",
    "Taurus": "♉",
    "Gemini": "♊",
    "Cancer": "♋",
    "Leo": "♌",
    "Virgo": "♍",
    "Libra": "♎",
    "Scorpio": "♏",
    "Sagittarius": "♐",
    "Capricorn": "♑",
    "Aquarius": "♒",
    "Pisces": "♓",
}

ASPECT_GLYPHS: dict[str, str] = {
    "conjunction": "☌",
    "opposition": "☍",
    "square": "□",
    "trine": "△",
    "sextile": "✳",
}

ASPECT_ASCII: dict[str, str] = {
    "conjunction": "CNJ",
    "opposition": "OPP",
    "square": "SQR",
    "trine": "TRI",
    "sextile": "SXT",
}

ELEMENT_GLYPHS: dict[str, str] = {
    "fire": "△",
    "water": "▽",
    "air": "△̵",
    "earth": "▽̵",
    "spirit": "○",
}

#: Used by the Wheel's rotating rim, in zodiacal order.
WHEEL_RIM_GLYPHS: tuple[str, ...] = tuple(SIGN_GLYPHS.values())
WHEEL_RIM_ASCII: tuple[str, ...] = tuple("ABCDEFGHIJKL")

#: Three-letter sign names, in the same zodiacal order as the rim. The
#: Wheel draws these under each glyph when it has the room (M12.4): a
#: terminal cannot scale a glyph, so a symbol is made *larger* by giving
#: it more cells, and a name is the most useful thing to fill them with.
WHEEL_RIM_LABELS: tuple[str, ...] = tuple(name[:3].upper() for name in SIGN_GLYPHS)


@dataclass(frozen=True)
class GlyphSet:
    """Resolves symbolic names to renderable text.

    Never raises on an unknown name - an unrecognized body or aspect is
    rendered as its own name, which is always readable, rather than
    blowing up a screen mid-render.
    """

    unicode: bool = True

    def body(self, name: str) -> str:
        table = PLANET_GLYPHS if self.unicode else PLANET_ASCII
        return table.get(name, name[:2].upper())

    def sign(self, name: str) -> str:
        if not self.unicode:
            return name[:3].upper()
        return SIGN_GLYPHS.get(name, name[:3].upper())

    def aspect(self, name: str) -> str:
        table = ASPECT_GLYPHS if self.unicode else ASPECT_ASCII
        return table.get(name, name[:3].upper())

    def element(self, name: str) -> str:
        if not self.unicode:
            return name[:3].upper()
        return ELEMENT_GLYPHS.get(name, name[:3].upper())

    @property
    def rim(self) -> tuple[str, ...]:
        return WHEEL_RIM_GLYPHS if self.unicode else WHEEL_RIM_ASCII

    @property
    def rim_labels(self) -> tuple[str, ...]:
        return WHEEL_RIM_LABELS


UNICODE_GLYPHS = GlyphSet(unicode=True)
ASCII_GLYPHS = GlyphSet(unicode=False)


def _stream_supports_unicode() -> bool:
    """Best-effort check of whether the output stream can render our
    glyphs, without ever raising - an encoding lookup failing is itself
    evidence the environment is unusual enough to fall back on.
    """
    encoding = getattr(sys.stdout, "encoding", None)
    if not encoding:
        try:
            encoding = locale.getpreferredencoding(False)
        except Exception:
            return False
    return "utf" in encoding.lower()


def default_glyphs() -> GlyphSet:
    """The glyph set for this session.

    `SYZYGY_ASCII=1` always forces the fallback set; otherwise this is
    real (if best-effort) terminal capability detection via the output
    stream's encoding, not a blanket assumption of Unicode support.
    """
    if os.environ.get("SYZYGY_ASCII") == "1":
        return ASCII_GLYPHS
    return UNICODE_GLYPHS if _stream_supports_unicode() else ASCII_GLYPHS


def format_degrees(longitude: float) -> str:
    """Position within its sign, as degrees and arcminutes: `14°22'`."""
    within_sign = longitude % 30
    degrees = int(within_sign)
    minutes = int(round((within_sign - degrees) * 60))
    if minutes == 60:  # rounding carried into the next degree
        degrees, minutes = degrees + 1, 0
    return f"{degrees}°{minutes:02d}'"


def format_orb(orb_degrees: float) -> str:
    """An aspect orb as degrees and arcminutes: `0°48'`."""
    degrees = int(abs(orb_degrees))
    minutes = int(round((abs(orb_degrees) - degrees) * 60))
    if minutes == 60:
        degrees, minutes = degrees + 1, 0
    return f"{degrees}°{minutes:02d}'"


class Glyph(Static):
    """One glyph with a label, e.g. `☉ Sun  Virgo 14°22'`.

    A widget rather than a formatted string so screens can style, animate,
    and query individual placements (`#glyph-sun`) without re-rendering a
    whole panel.
    """

    def __init__(
        self,
        symbol: str,
        label: str,
        value: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        text = f"{symbol} {label}" if not value else f"{symbol} {label:<10} {value}"
        super().__init__(text, id=id, classes=classes)
        self.symbol = symbol
        self.label = label
        self.value = value
