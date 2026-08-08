"""Tests for the narrow interpretation context assembly rules."""

from datetime import UTC, datetime
from inspect import signature

from syzygy.domain.astrology import (
    BirthData,
    NatalChart,
    NatalPlacement,
    RankedTransit,
    TransitAspect,
)
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.profile import Profile
from syzygy.interpretation.context_builder import build_context
from syzygy.sortes.deck import get_card

CONSULTATION_TIMESTAMP = "2026-08-07T08:00:00-04:00"
CONSULTATION_DATE = "2026-08-07"


def _profile() -> Profile:
    birth_data = BirthData(
        local_date="1990-08-07",
        local_time="14:22:00",
        place_label="New York, NY",
        latitude=40.7128,
        longitude=-74.006,
        timezone="America/New_York",
    )
    natal_chart = NatalChart(
        birth_data=birth_data,
        placements=[
            NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
            NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
            NatalPlacement(body="Mercury", sign="Aries", longitude=5.0, house=1),
            NatalPlacement(body="Venus", sign="Aries", longitude=18.0, house=1),
            NatalPlacement(body="Mars", sign="Scorpio", longitude=220.0, house=8),
            NatalPlacement(body="Jupiter", sign="Taurus", longitude=45.0, house=2),
        ],
        # No Ascendant/Midheaven placements: `KerykeionAstrologyEngine`
        # returns exactly the ten transit bodies and carries the angles as
        # `ascendant_longitude`/`midheaven_longitude`. A fixture that
        # invented angle placements would let the builder depend on a field
        # the real engine never produces.
        aspects=[],
        ascendant_longitude=15.0,
        midheaven_longitude=285.0,
        astrology_engine="fixture",
        astrology_engine_version="fixture-v1",
        chart_schema_version="chart-v1",
    )
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    return Profile(
        id="p1",
        display_name="Blake",
        birth_data=birth_data,
        natal_chart=natal_chart,
        created_at_utc=now,
        updated_at_utc=now,
    )


def _chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        id="chunk-1",
        source_id="book-of-thoth",
        section_id="the-high-priestess",
        section_type="card",
        card_id="the_high_priestess",
        title="The High Priestess",
        page_start=10,
        page_end=10,
        chunk_index=0,
        text="A fixture knowledge chunk.",
        text_hash="hash-1",
    )


def _transit(natal_target: str) -> RankedTransit:
    return RankedTransit(
        aspect=TransitAspect(
            transiting_body="Saturn",
            natal_target=natal_target,
            aspect="square",
            orb_degrees=0.84,
            movement="applying",
        ),
        score=9.2,
        rank=1,
    )


def _build(card_id: str, ranked_transits: list[RankedTransit] | None = None):
    return build_context(
        profile=_profile(),
        card=get_card(card_id),
        ranked_transits=[] if ranked_transits is None else ranked_transits,
        knowledge_chunks=[_chunk()],
        consultation_local_timestamp=CONSULTATION_TIMESTAMP,
        consultation_local_date=CONSULTATION_DATE,
        prompt_version="daily-v1",
    )


def _bodies(context) -> set[str]:
    return {placement.body for placement in context.relevant_natal_placements}


def test_planet_attributed_card_includes_its_natal_placement():
    context = _build("the_high_priestess")

    assert context.card.astrology is not None
    assert context.card.astrology.type == "planet"
    assert any(
        placement.body == "Moon"
        for placement in context.relevant_natal_placements
    )


def test_sign_attributed_card_includes_every_natal_placement_in_that_sign():
    profile = _profile()
    context = build_context(
        profile,
        get_card("the_emperor"),
        [],
        [_chunk()],
        CONSULTATION_TIMESTAMP,
        CONSULTATION_DATE,
        "daily-v1",
    )
    aries_placements = [
        placement for placement in profile.natal_chart.placements if placement.sign == "Aries"
    ]

    assert all(placement in context.relevant_natal_placements for placement in aries_placements)


def test_decan_attributed_card_includes_its_ruling_planet_placement():
    context = _build("two_of_wands")

    assert _bodies(context) == {"Sun", "Moon", "Mars"}


def test_card_without_astrology_has_only_the_base_placement_set():
    context = _build("princess_of_wands")

    assert context.card.astrology is None
    assert _bodies(context) == {"Sun", "Moon"}


def test_transit_to_a_natal_angle_does_not_fabricate_a_placement():
    # The angles have no `NatalPlacement` to include; the Ascendant reaches
    # the model as `ascendant_sign`, and the transit itself names the angle.
    context = _build("princess_of_wands", [_transit("Ascendant"), _transit("Midheaven")])

    assert _bodies(context) == {"Sun", "Moon"}
    assert context.ascendant_sign == "Aries"
    assert [t.aspect.natal_target for t in context.significant_transits] == [
        "Ascendant",
        "Midheaven",
    ]


def test_context_builder_signature_is_the_narrow_design_surface():
    assert list(signature(build_context).parameters) == [
        "profile",
        "card",
        "ranked_transits",
        "knowledge_chunks",
        "consultation_local_timestamp",
        "consultation_local_date",
        "prompt_version",
    ]


def test_ranked_transits_are_passed_through_without_filtering_or_reranking():
    ranked_transits = [_transit("Venus"), _transit("Midheaven")]

    context = _build("princess_of_wands", ranked_transits)

    assert context.significant_transits == ranked_transits
    assert [transit.rank for transit in context.significant_transits] == [1, 1]


def test_relevant_placements_are_deduplicated_by_body():
    context = _build("the_high_priestess", [_transit("Moon")])

    assert [placement.body for placement in context.relevant_natal_placements].count("Moon") == 1
