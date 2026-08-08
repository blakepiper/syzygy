"""Tests for the versioned prompt contract (IMPLEMENTATION_PLAN.md §7.3).

The prompt's *prose* is not asserted line by line - it is meant to be
edited. What is asserted is the contract around it: the version string,
that every fact on the context reaches the model, that absent facts are
stated as absent rather than silently omitted, and that the advertised
output schema cannot drift from `InterpretationResult`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from syzygy.domain.astrology import (
    BirthData,
    NatalChart,
    NatalPlacement,
    RankedTransit,
    TransitAspect,
)
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.profile import Profile
from syzygy.interpretation.context_builder import build_context
from syzygy.interpretation.prompts import (
    PROMPT_VERSION,
    PROVENANCE_FIELDS,
    RESPONSE_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_user_prompt,
)
from syzygy.sortes.deck import get_card

BIRTH_PLACE = "Alexandria, Virginia, USA"
CONSULTATION_TIMESTAMP = "2026-08-07T08:00:00-04:00"
CONSULTATION_DATE = "2026-08-07"


def _profile() -> Profile:
    birth_data = BirthData(
        local_date="1990-08-07",
        local_time="14:22:00",
        place_label=BIRTH_PLACE,
        latitude=38.8048,
        longitude=-77.0469,
        timezone="America/New_York",
    )
    natal_chart = NatalChart(
        birth_data=birth_data,
        placements=[
            NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
            NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
            NatalPlacement(body="Mars", sign="Scorpio", longitude=220.0, house=8, retrograde=True),
            NatalPlacement(body="Venus", sign="Aries", longitude=18.5, house=1),
        ],
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


def _chunk(chunk_id: str = "chunk-1") -> KnowledgeChunk:
    return KnowledgeChunk(
        id=chunk_id,
        source_id="book-of-thoth",
        section_id="two-of-wands",
        section_type="card",
        card_id="two_of_wands",
        title="Two of Wands - Dominion",
        page_start=180,
        page_end=181,
        chunk_index=0,
        text="Dominion: the Will asserting itself, energetic and unembarrassed.",
        text_hash="hash-1",
    )


def _transit(natal_target: str = "Venus") -> RankedTransit:
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


def _context(
    card_id: str = "two_of_wands",
    *,
    transits: list[RankedTransit] | None = None,
    chunks: list[KnowledgeChunk] | None = None,
) -> InterpretationContext:
    return build_context(
        profile=_profile(),
        card=get_card(card_id),
        ranked_transits=[_transit()] if transits is None else transits,
        knowledge_chunks=[_chunk()] if chunks is None else chunks,
        consultation_local_timestamp=CONSULTATION_TIMESTAMP,
        consultation_local_date=CONSULTATION_DATE,
        prompt_version=PROMPT_VERSION,
    )


def test_prompt_version_is_the_documented_constant():
    assert PROMPT_VERSION == "daily-v1"


def test_rendering_is_deterministic():
    assert build_user_prompt(_context()) == build_user_prompt(_context())


def test_every_supplied_fact_reaches_the_model():
    prompt = build_user_prompt(_context())

    assert "Blake" in prompt
    assert CONSULTATION_DATE in prompt
    assert CONSULTATION_TIMESTAMP in prompt
    assert "Two of Wands - Dominion" in prompt
    assert "two_of_wands" in prompt
    assert "Mars in Aries" in prompt  # the decan's planet/sign pairing
    assert "transiting Saturn square natal Venus" in prompt
    assert "0.84" in prompt
    assert "applying" in prompt
    assert "Sun: 15°00' Leo, house 10" in prompt
    assert "Moon: 8°00' Pisces, house 4" in prompt
    assert "Ascendant sign: Aries" in prompt
    assert "[chunk-1]" in prompt
    assert "unembarrassed" in prompt
    assert "pages 180-181" in prompt


def test_retrograde_and_house_are_rendered_when_present():
    context = _context(transits=[_transit("Mars")])

    assert "Mars: 10°00' Scorpio, house 8, retrograde" in build_user_prompt(context)


def test_luminaries_are_rendered_once_as_anchors():
    prompt = build_user_prompt(_context("the_hermit", transits=[]))

    assert prompt.count("Sun: 15°00' Leo") == 1
    assert prompt.count("Moon: 8°00' Pisces") == 1
    assert "none beyond the anchors above" in prompt


def test_prompt_contains_nothing_the_context_does_not_carry():
    # The context is the entire input surface (DESIGN.md §12/§13.3): birth
    # place and coordinates live on the profile and must never be sent.
    prompt = build_user_prompt(_context())

    assert BIRTH_PLACE not in prompt
    assert "38.80" not in prompt
    assert "-77.04" not in prompt
    assert "1990-08-07" not in prompt


def test_an_empty_sky_is_stated_rather_than_omitted():
    prompt = build_user_prompt(_context(transits=[]))

    assert "SIGNIFICANT TRANSITS TODAY" in prompt
    assert "none within orb today" in prompt


def test_absent_source_material_is_stated_rather_than_omitted():
    # DESIGN.md §23: never let the model imply Crowley grounding it never got.
    prompt = build_user_prompt(_context(chunks=[]))

    assert "none supplied" in prompt


def test_a_card_without_zodiacal_attribution_says_so_explicitly():
    prompt = build_user_prompt(_context("princess_of_disks"))

    assert "no zodiacal attribution" in prompt
    assert "do not supply one" in prompt


def test_court_card_renders_its_counter_elemental_span():
    prompt = build_user_prompt(_context("knight_of_wands"))

    assert "21° Scorpio - 20° Sagittarius" in prompt


def test_major_arcana_renders_its_sign_and_hebrew_letter():
    prompt = build_user_prompt(_context("the_hermit"))

    assert "correspondence: sign Virgo" in prompt
    assert "Hebrew letter: Yod" in prompt


def test_response_schema_is_the_domain_model_minus_provenance():
    expected = set(InterpretationResult.model_fields) - set(PROVENANCE_FIELDS)

    assert set(RESPONSE_JSON_SCHEMA["properties"]) == expected
    assert set(RESPONSE_JSON_SCHEMA["required"]) == expected
    assert RESPONSE_JSON_SCHEMA["additionalProperties"] is False


def test_a_reply_matching_the_schema_validates_once_provenance_is_added():
    reply = {
        "alignment_title": "Dominion under a hard Saturn",
        "esoteric": {"summary": "A summary.", "body": "A body."},
        "conventional": {
            "summary": "A summary.",
            "body": "A body.",
            "watch_for": ["One thing."],
            "reflection": "A question?",
        },
        "source_chunk_ids": ["chunk-1"],
    }

    result = InterpretationResult.model_validate(
        {**reply, "provider_id": "p", "model_id": "m", "prompt_version": PROMPT_VERSION}
    )

    assert result.conventional.watch_for == ["One thing."]
    assert result.source_chunk_ids == ["chunk-1"]


def test_system_prompt_states_the_same_output_keys_as_the_schema():
    # The prompt spells the shape out inline for providers that cannot
    # constrain output natively; the two must not drift apart.
    for key in RESPONSE_JSON_SCHEMA["properties"]:
        assert f'"{key}"' in SYSTEM_PROMPT
    for field in PROVENANCE_FIELDS:
        assert field not in SYSTEM_PROMPT


def test_repair_prompt_carries_the_error_and_the_rejected_output():
    prompt = build_repair_prompt(json.dumps({"nope": 1}), "1 validation error for ...")

    assert '{"nope": 1}' in prompt
    assert "1 validation error for ..." in prompt
    assert "single JSON object" in prompt
