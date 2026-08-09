"""Canonical I Ching reference data and an immutable six-line cast."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Trigram(StrEnum):
    HEAVEN = "heaven"
    EARTH = "earth"
    THUNDER = "thunder"
    WATER = "water"
    MOUNTAIN = "mountain"
    WIND = "wind"
    FIRE = "fire"
    LAKE = "lake"


class LinePolarity(StrEnum):
    YIN = "yin"
    YANG = "yang"


class IChingCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    text_pages: str
    image_pages: str
    source_url: str


class Hexagram(BaseModel):
    """One King Wen hexagram, transcribed from Legge's 1882 edition."""

    model_config = ConfigDict(frozen=True)

    id: str
    number: int = Field(ge=1, le=64)
    king_wen_sequence: int = Field(ge=1, le=64)
    name: str
    unicode: str = Field(min_length=1, max_length=1)
    lower_trigram: Trigram
    upper_trigram: Trigram
    lines_bottom_up: list[LinePolarity] = Field(min_length=6, max_length=6)
    judgment: str
    image: str
    line_texts: list[str] = Field(min_length=6, max_length=6)
    citation: IChingCitation

    @model_validator(mode="after")
    def validate_identity(self) -> Hexagram:
        if self.number != self.king_wen_sequence:
            raise ValueError("number must equal the King Wen sequence position")
        if self.id != f"hexagram-{self.number:02d}":
            raise ValueError("hexagram id must be derived from its number")
        if ord(self.unicode) != 0x4DBF + self.number:
            raise ValueError("unicode symbol must match the King Wen number")
        return self


class IChingLineValue(IntEnum):
    OLD_YIN = 6
    YOUNG_YANG = 7
    YOUNG_YIN = 8
    OLD_YANG = 9

    @property
    def polarity(self) -> LinePolarity:
        return LinePolarity.YANG if self in (self.YOUNG_YANG, self.OLD_YANG) else LinePolarity.YIN

    @property
    def is_changing(self) -> bool:
        return self in (self.OLD_YIN, self.OLD_YANG)


class IChingCast(BaseModel):
    """The committed result of one three-coin cast, bottom line first."""

    model_config = ConfigDict(frozen=True)

    lines: list[IChingLineValue] = Field(min_length=6, max_length=6)
    primary_hexagram_number: int = Field(ge=1, le=64)
    changing_lines: list[int]
    resulting_hexagram_number: int = Field(ge=1, le=64)
    cast_at_utc: datetime
    method_version: str
    entropy_digest: str

    @model_validator(mode="after")
    def validate_changing_lines(self) -> IChingCast:
        expected = [index for index, line in enumerate(self.lines, start=1) if line.is_changing]
        if self.changing_lines != expected:
            raise ValueError("changing_lines must be derived from line values")
        return self
