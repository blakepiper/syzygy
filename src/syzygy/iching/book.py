"""Load and validate the source-grounded canonical 64 hexagrams."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

from syzygy.domain.iching import Hexagram, LinePolarity, Trigram

EXPECTED_HEXAGRAM_COUNT = 64


class HexagramValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_hexagrams() -> tuple[Hexagram, ...]:
    raw = resources.files("syzygy.resources").joinpath("iching_legge.yaml").read_text("utf-8")
    data = yaml.safe_load(raw)
    hexagrams = tuple(Hexagram.model_validate(item) for item in data["hexagrams"])
    _validate(hexagrams)
    return hexagrams


def _validate(hexagrams: tuple[Hexagram, ...]) -> None:
    if len(hexagrams) != EXPECTED_HEXAGRAM_COUNT:
        raise HexagramValidationError(
            f"expected {EXPECTED_HEXAGRAM_COUNT} hexagrams, got {len(hexagrams)}"
        )
    numbers = [item.number for item in hexagrams]
    if numbers != list(range(1, EXPECTED_HEXAGRAM_COUNT + 1)):
        raise HexagramValidationError("hexagrams must appear once each in King Wen order")
    patterns = [tuple(item.lines_bottom_up) for item in hexagrams]
    if len(set(patterns)) != EXPECTED_HEXAGRAM_COUNT:
        raise HexagramValidationError("each of the 64 line patterns must appear exactly once")
    for item in hexagrams:
        lower = _trigram_for(item.lines_bottom_up[:3])
        upper = _trigram_for(item.lines_bottom_up[3:])
        if (item.lower_trigram, item.upper_trigram) != (lower, upper):
            raise HexagramValidationError(f"trigram labels do not match {item.id}'s lines")


_TRIGRAMS: dict[tuple[LinePolarity, ...], Trigram] = {
    (LinePolarity.YANG, LinePolarity.YANG, LinePolarity.YANG): Trigram.HEAVEN,
    (LinePolarity.YIN, LinePolarity.YIN, LinePolarity.YIN): Trigram.EARTH,
    (LinePolarity.YANG, LinePolarity.YIN, LinePolarity.YIN): Trigram.THUNDER,
    (LinePolarity.YIN, LinePolarity.YANG, LinePolarity.YIN): Trigram.WATER,
    (LinePolarity.YIN, LinePolarity.YIN, LinePolarity.YANG): Trigram.MOUNTAIN,
    (LinePolarity.YIN, LinePolarity.YANG, LinePolarity.YANG): Trigram.WIND,
    (LinePolarity.YANG, LinePolarity.YIN, LinePolarity.YANG): Trigram.FIRE,
    (LinePolarity.YANG, LinePolarity.YANG, LinePolarity.YIN): Trigram.LAKE,
}


def _trigram_for(lines: list[LinePolarity]) -> Trigram:
    return _TRIGRAMS[tuple(lines)]


def get_hexagram(number: int) -> Hexagram:
    if not 1 <= number <= EXPECTED_HEXAGRAM_COUNT:
        raise KeyError(f"unknown hexagram number: {number}")
    return load_hexagrams()[number - 1]


def number_for_lines(lines: list[LinePolarity]) -> int:
    pattern = tuple(lines)
    for hexagram in load_hexagrams():
        if tuple(hexagram.lines_bottom_up) == pattern:
            return hexagram.number
    raise KeyError(f"unknown hexagram line pattern: {pattern!r}")
