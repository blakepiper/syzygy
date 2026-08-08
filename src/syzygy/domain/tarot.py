"""Tarot domain models: the canonical Thoth deck and a single day's draw.

Canonical card data lives in `src/syzygy/resources/thoth_deck.yaml` and is
loaded by `syzygy.sortes.deck`. This module only defines the shapes.

v0.1 draws upright cards only (DESIGN.md section 8.1) - there is
deliberately no `orientation`/`reversed` field anywhere in this module.
Do not add one; see AGENTS.md.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Arcana(StrEnum):
    MAJOR = "major"
    MINOR = "minor"


class Suit(StrEnum):
    WANDS = "wands"
    CUPS = "cups"
    SWORDS = "swords"
    DISKS = "disks"


class CourtRank(StrEnum):
    KNIGHT = "knight"
    QUEEN = "queen"
    PRINCE = "prince"
    PRINCESS = "princess"


class Element(StrEnum):
    FIRE = "fire"
    WATER = "water"
    AIR = "air"
    EARTH = "earth"
    SPIRIT = "spirit"


class Decan(BaseModel):
    """A single 10-degree decan of a numbered Minor Arcana card (rank 2-10)."""

    model_config = ConfigDict(frozen=True)

    sign: str
    index: int = Field(ge=1, le=3)
    start_degree: int = Field(ge=0, le=20)
    end_degree: int = Field(ge=10, le=30)


class CourtSpan(BaseModel):
    """The counter-elemental zodiac span a court card rules.

    Spans the last decan of `start_sign` through the first two decans of
    `end_sign` (e.g. 21 degrees Scorpio - 20 degrees Sagittarius for the
    Knight of Wands). See docs/THOTH_INGESTION_MAP.md section 11 for why
    this is not simply "the suit's own triplicity sign".
    """

    model_config = ConfigDict(frozen=True)

    start_sign: str
    start_degree: int
    end_sign: str
    end_degree: int


class AstrologyCorrespondence(BaseModel):
    """A card's astrological attribution. Exactly one of the value fields
    is populated, selected by `type`. Absent (None) for the four Princess
    cards, which the source text states explicitly have no zodiacal
    attribution - see docs/THOTH_INGESTION_MAP.md section 11.
    """

    model_config = ConfigDict(frozen=True)

    type: str  # "element" | "planet" | "sign" | "decan" | "court_decan_span"
    planet: str | None = None
    sign: str | None = None
    decan: Decan | None = None
    court_span: CourtSpan | None = None


class Qabalah(BaseModel):
    model_config = ConfigDict(frozen=True)

    sephira: str | None = None
    path_number: int | None = None


class TarotCard(BaseModel):
    """One of the 78 canonical Thoth cards. Immutable reference data."""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    full_name: str
    arcana: Arcana
    roman_numeral: str | None = None
    suit: Suit | None = None
    rank: int | None = Field(default=None, ge=1, le=10)
    court: CourtRank | None = None
    element: Element | None = None
    sub_element: Element | None = None
    hebrew_letter: str | None = None
    hebrew_letter_type: str | None = None
    tetragrammaton_letter: str | None = None
    astrology: AstrologyCorrespondence | None = None
    qabalah: Qabalah
    book_of_thoth_aliases: list[str] = Field(default_factory=list)


class TarotDraw(BaseModel):
    """The immutable result of one Sortes draw for one reading.

    Persisted verbatim once written; see `syzygy.domain.reading.Reading`
    for the invariant that this must be committed before interpretation
    begins.
    """

    model_config = ConfigDict(frozen=True)

    card_id: str
    drawn_at_utc: datetime
    sortes_version: str
    entropy_digest: str
