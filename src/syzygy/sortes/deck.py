"""Loads and validates the canonical 78-card Thoth deck.

`src/syzygy/resources/thoth_deck.yaml` is the single source of truth for
card data (docs/old/DESIGN.md section 8.2). This module only loads and validates
it; it does not know anything about drawing or randomness (see
`syzygy.sortes.draw` for that).
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

from syzygy.domain.tarot import TarotCard

EXPECTED_CARD_COUNT = 78
EXPECTED_MAJOR_COUNT = 22
EXPECTED_MINOR_COUNT = 56
EXPECTED_COURT_COUNT = 16
EXPECTED_SUIT_SIZE = 14  # ace..ten (10) + 4 court cards


class DeckValidationError(ValueError):
    """Raised when `thoth_deck.yaml` fails a structural invariant check."""


def _load_raw() -> list[dict]:
    package_files = resources.files("syzygy.resources")
    raw_text = package_files.joinpath("thoth_deck.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    return data["cards"]


def _validate(cards: list[TarotCard]) -> None:
    if len(cards) != EXPECTED_CARD_COUNT:
        raise DeckValidationError(f"expected {EXPECTED_CARD_COUNT} cards, got {len(cards)}")

    ids = [c.id for c in cards]
    if len(set(ids)) != len(ids):
        duplicates = {i for i in ids if ids.count(i) > 1}
        raise DeckValidationError(f"duplicate card ids: {duplicates}")

    majors = [c for c in cards if c.arcana == "major"]
    minors = [c for c in cards if c.arcana == "minor"]
    if len(majors) != EXPECTED_MAJOR_COUNT:
        raise DeckValidationError(f"expected {EXPECTED_MAJOR_COUNT} major cards, got {len(majors)}")
    if len(minors) != EXPECTED_MINOR_COUNT:
        raise DeckValidationError(f"expected {EXPECTED_MINOR_COUNT} minor cards, got {len(minors)}")

    courts = [c for c in minors if c.court is not None]
    if len(courts) != EXPECTED_COURT_COUNT:
        raise DeckValidationError(f"expected {EXPECTED_COURT_COUNT} court cards, got {len(courts)}")

    for suit in ("wands", "cups", "swords", "disks"):
        suit_cards = [c for c in minors if c.suit == suit]
        if len(suit_cards) != EXPECTED_SUIT_SIZE:
            raise DeckValidationError(
                f"suit {suit!r} has {len(suit_cards)} cards, expected {EXPECTED_SUIT_SIZE}"
            )

    for court in ("knight", "queen", "prince", "princess"):
        court_cards = [c for c in courts if c.court == court]
        if len(court_cards) != 4:
            raise DeckValidationError(
                f"court rank {court!r} has {len(court_cards)} cards, expected 4"
            )


@lru_cache(maxsize=1)
def load_deck() -> tuple[TarotCard, ...]:
    """Load, validate, and cache the canonical 78-card deck.

    Raises `DeckValidationError` if `thoth_deck.yaml` fails any structural
    invariant. Cached because this is reference data - the file is not
    expected to change at runtime.
    """
    cards = tuple(TarotCard.model_validate(raw) for raw in _load_raw())
    _validate(list(cards))
    return cards


def get_card(card_id: str) -> TarotCard:
    """Look up one card by its stable id. Raises `KeyError` if unknown."""
    for card in load_deck():
        if card.id == card_id:
            return card
    raise KeyError(f"unknown card id: {card_id!r}")
