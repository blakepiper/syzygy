import pytest

from syzygy.domain.astrology import NatalPlacement, RankedTransit, TransitAspect
from syzygy.domain.interpretation import InterpretationContext
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.deck import get_card


def _context(card_id: str = "two_of_wands") -> InterpretationContext:
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


@pytest.mark.asyncio
async def test_fixture_provider_returns_a_valid_result():
    provider = FixtureProvider()
    result = await provider.interpret(_context())

    assert result.provider_id == "fixture"
    assert result.esoteric.body
    assert result.conventional.body
    assert result.conventional.reflection
    assert "Two of Wands" in result.alignment_title or "Dominion" in result.alignment_title


@pytest.mark.asyncio
async def test_fixture_provider_is_deterministic():
    provider = FixtureProvider()
    context = _context()
    result_a = await provider.interpret(context)
    result_b = await provider.interpret(context)
    assert result_a == result_b


@pytest.mark.asyncio
async def test_fixture_provider_mentions_the_significant_transit():
    provider = FixtureProvider()
    result = await provider.interpret(_context())
    assert "Saturn" in result.esoteric.body
    assert "Venus" in result.esoteric.body


@pytest.mark.asyncio
async def test_fixture_provider_handles_a_card_with_no_astrology():
    # Princess of Disks has astrology=None (docs/THOTH_INGESTION_MAP.md 11)
    # - the provider must not crash on this documented edge case.
    provider = FixtureProvider()
    result = await provider.interpret(_context(card_id="princess_of_disks"))
    assert result.esoteric.body
