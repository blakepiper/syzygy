from __future__ import annotations

import pytest

from syzygy.domain.astrology import NatalPlacement, RankedTransit, TransitAspect
from syzygy.domain.interpretation import InterpretationContext
from syzygy.sortes.deck import get_card


def build_sample_context(card_id: str = "two_of_wands") -> InterpretationContext:
    card = get_card(card_id)
    sun = NatalPlacement(body="Sun", sign="Virgo", longitude=141.0, house=10)
    moon = NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4)
    transit = RankedTransit(
        aspect=TransitAspect(
            transiting_body="Saturn",
            natal_target="Venus",
            aspect="square",
            orb_degrees=0.84,
            movement="applying",
        ),
        score=9.2,
        rank=1,
    )
    return InterpretationContext(
        profile_display_name="Blake",
        consultation_local_date="2026-08-07",
        consultation_local_timestamp="2026-08-07T08:00:00-04:00",
        card=card,
        significant_transits=[transit],
        relevant_natal_placements=[sun, moon],
        sun_placement=sun,
        moon_placement=moon,
        ascendant_sign="Scorpio",
        knowledge_chunks=[],
        prompt_version="daily-v1",
    )


@pytest.fixture
def sample_context() -> InterpretationContext:
    return build_sample_context()
