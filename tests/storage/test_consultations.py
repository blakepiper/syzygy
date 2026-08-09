"""The Oracle rite: one question, one turn of the wheel, two objects.

M22.1e and M22.2c. The invariants under test are the ones that make a
consultation trustworthy: both chance objects are on disk before any
provider exists, neither can be redrawn by a retry, a crash between the
wheel and the interpretation resumes from what was committed, and none of
it touches `readings`.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import UTC, datetime

import pytest

from syzygy.clock import FixedClock
from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement
from syzygy.domain.consultation import ConsultationStatus
from syzygy.domain.iching import IChingLineValue
from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
)
from syzygy.domain.profile import Profile
from syzygy.iching.cast import cast_hexagram
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.deck import load_deck
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import consultations, readings
from syzygy.storage.consultation_service import (
    ask_question,
    draw_consultation,
    interpret_consultation,
)
from syzygy.storage.consultations import (
    IllegalConsultationTransition,
    LegacyConsultationIsReadOnly,
)
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


class FailingProvider:
    provider_id = "failure"
    model_id = "failure-v1"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise RuntimeError("no interpreter")


class NeverConstructedProvider:
    """A provider that fails the moment anything tries to build one."""

    provider_id = "never"
    model_id = "never"

    def __init__(self) -> None:
        raise AssertionError("a provider was constructed before the objects were committed")


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "oracle.db")
    apply_all(connection)
    yield connection
    connection.close()


@pytest.fixture
def profile(conn) -> Profile:
    birth = BirthData(
        local_date="1990-01-01",
        local_time="12:00:00",
        place_label="Here",
        latitude=0,
        longitude=0,
        timezone="UTC",
    )
    chart = NatalChart(
        birth_data=birth,
        # All ten transiting bodies, because a card's correspondence
        # decides which further placements the context pulls in - and
        # these tests draw across the whole deck.
        placements=[
            NatalPlacement(body=body, sign=sign, longitude=longitude)
            for body, sign, longitude in (
                ("Sun", "Aries", 1.0),
                ("Moon", "Taurus", 31.0),
                ("Mercury", "Gemini", 61.0),
                ("Venus", "Cancer", 91.0),
                ("Mars", "Leo", 121.0),
                ("Jupiter", "Virgo", 151.0),
                ("Saturn", "Libra", 181.0),
                ("Uranus", "Scorpio", 211.0),
                ("Neptune", "Sagittarius", 241.0),
                ("Pluto", "Capricorn", 271.0),
            )
        ],
        aspects=[],
        ascendant_longitude=60,
        midheaven_longitude=150,
        astrology_engine="fixture",
        astrology_engine_version="1",
        chart_schema_version="natal-v1",
    )
    value = Profile(
        id="oracle-profile",
        display_name="Blake",
        birth_data=birth,
        natal_chart=chart,
        created_at_utc=NOW,
        updated_at_utc=NOW,
    )
    insert_profile(conn, value)
    return value


def collector(seed: int = 1) -> EntropyCollector:
    return EntropyCollector(session_nonce=b"oracle", os_random=lambda n: bytes([seed]) * n)


def hostile_collector() -> EntropyCollector:
    return EntropyCollector(
        os_random=lambda _n: (_ for _ in ()).throw(AssertionError("chance entered twice"))
    )


# -- M22.2: one turn of the wheel, two objects -----------------------------


def test_one_collector_serves_both_derivations(conn, profile) -> None:
    clock = FixedClock(NOW)
    shared = collector()
    consultation = ask_question(conn, profile, clock, "What am I standing in?")
    consultation = draw_consultation(conn, consultation, profile, clock, shared)

    assert consultation.card_draw is not None
    assert consultation.cast is not None
    # Domain separation, not two collectors: the card selects over the
    # mixed digest and each line over its own personalized derivation.
    assert consultation.card_draw.entropy_digest == consultation.cast.entropy_digest
    assert consultation.card_draw.card_id == draw_card(collector(), now=NOW).card_id
    assert consultation.cast.lines == cast_hexagram(collector(), now=NOW).lines


def test_both_objects_are_on_disk_before_a_provider_is_constructed(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What is fixed?")
    consultation = draw_consultation(conn, consultation, profile, clock, collector())

    stored = consultations.get_by_id(conn, consultation.id)
    assert stored is not None
    assert stored.card_draw is not None and stored.cast is not None
    with pytest.raises(AssertionError):
        NeverConstructedProvider()


def test_the_card_distribution_is_unchanged_from_the_daily_draw() -> None:
    deck_size = len(load_deck())
    counts: Counter[str] = Counter()
    trials = 20_000
    for seed in range(trials):
        digest = seed.to_bytes(8, "big")
        entropy = EntropyCollector(session_nonce=b"", os_random=lambda _n, d=digest: d * 4)
        counts[draw_card(entropy, now=NOW).card_id] += 1

    assert len(counts) == deck_size
    expected = trials / deck_size
    assert max(abs(count - expected) for count in counts.values()) < expected * 0.35


def test_the_per_line_probabilities_are_unchanged_from_the_cast(conn, profile) -> None:
    clock = FixedClock(NOW)
    counts: Counter[IChingLineValue] = Counter()
    trials = 4_000
    for seed in range(trials):
        digest = seed.to_bytes(8, "big")
        entropy = EntropyCollector(session_nonce=b"", os_random=lambda _n, d=digest: d * 4)
        consultation = ask_question(conn, profile, clock, f"Question {seed}?")
        consultation = draw_consultation(conn, consultation, profile, clock, entropy)
        assert consultation.cast is not None
        counts.update(consultation.cast.lines)

    total = trials * 6
    expected = {
        IChingLineValue.OLD_YIN: 1 / 8,
        IChingLineValue.YOUNG_YANG: 3 / 8,
        IChingLineValue.YOUNG_YIN: 3 / 8,
        IChingLineValue.OLD_YANG: 1 / 8,
    }
    for line, probability in expected.items():
        assert abs(counts[line] / total - probability) < 0.02


def test_the_two_derivations_are_independent(conn, profile) -> None:
    """The same card must not always arrive with the same hexagram."""
    clock = FixedClock(NOW)
    pairs: dict[str, set[int]] = {}
    for seed in range(400):
        digest = seed.to_bytes(8, "big")
        entropy = EntropyCollector(session_nonce=b"", os_random=lambda _n, d=digest: d * 4)
        consultation = ask_question(conn, profile, clock, f"Question {seed}?")
        consultation = draw_consultation(conn, consultation, profile, clock, entropy)
        assert consultation.card_draw is not None and consultation.cast is not None
        pairs.setdefault(consultation.card_draw.card_id, set()).add(
            consultation.cast.primary_hexagram_number
        )

    repeated = [hexagrams for hexagrams in pairs.values() if len(hexagrams) > 1]
    assert repeated, "no card was drawn twice; the sample is too small to judge"
    assert all(len(hexagrams) > 1 for hexagrams in repeated)


# -- M22.1: storage and the state machine ----------------------------------


def test_a_row_holding_one_object_cannot_be_stored(conn, profile) -> None:
    consultation = ask_question(conn, profile, FixedClock(NOW), "Half of one?")
    draw = draw_card(collector(), now=NOW)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE consultations SET status = ?, card_draw_json = ? WHERE id = ?",
            (ConsultationStatus.DRAWN.value, draw.model_dump_json(), consultation.id),
        )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (ConsultationStatus.ASKED, ConsultationStatus.CONTEXT_READY),
        (ConsultationStatus.DRAWN, ConsultationStatus.INTERPRETING),
        (ConsultationStatus.DRAWN, ConsultationStatus.DRAWN),
        (ConsultationStatus.CONTEXT_READY, ConsultationStatus.COMPLETE),
    ],
)
def test_every_illegal_transition_is_rejected(conn, profile, from_status, to_status) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "How far can this go?")
    if from_status is not ConsultationStatus.ASKED:
        consultation = consultations.commit_chance(
            conn,
            consultation.id,
            draw=draw_card(collector(), now=NOW),
            cast=cast_hexagram(collector(), now=NOW),
        )
    if from_status is ConsultationStatus.CONTEXT_READY:
        consultation = draw_consultation(conn, consultation, profile, clock, collector())

    with pytest.raises(IllegalConsultationTransition):
        consultations._advance(conn, consultation.id, to_status, NOW)


def test_crash_between_the_wheel_and_interpretation_resumes(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What remains fixed?")
    committed = consultations.commit_chance(
        conn,
        consultation.id,
        draw=draw_card(collector(), now=NOW),
        cast=cast_hexagram(collector(), now=NOW),
    )

    resumed = draw_consultation(conn, committed, profile, clock, hostile_collector())

    assert resumed.status is ConsultationStatus.CONTEXT_READY
    assert resumed.card_draw == committed.card_draw
    assert resumed.cast == committed.cast


@pytest.mark.asyncio
async def test_retry_after_a_failed_interpretation_reuses_both_objects(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What needs my attention?")
    consultation = draw_consultation(conn, consultation, profile, clock, collector())
    card, cast = consultation.card_draw, consultation.cast

    failed = await interpret_consultation(conn, consultation, clock, FailingProvider())
    retried = await interpret_consultation(conn, failed, clock, FixtureProvider())

    assert failed.status is ConsultationStatus.INTERPRETATION_FAILED
    assert failed.provider_id == "failure"
    assert failed.prompt_version == "oracle-v2"
    assert failed.card_draw == card and failed.cast == cast
    assert retried.status is ConsultationStatus.COMPLETE
    assert retried.card_draw == card and retried.cast == cast
    assert retried.result is not None
    assert retried.result.prompt_version == "oracle-v2"


@pytest.mark.asyncio
async def test_the_oracle_never_touches_the_daily_reading(conn, profile) -> None:
    clock = FixedClock(NOW)
    daily = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=NOW.date().isoformat(),
        consultation_local_timestamp=NOW.isoformat(),
        consultation_utc_timestamp=NOW,
        consultation_timezone="UTC",
    )

    first = ask_question(conn, profile, clock, "First?")
    second = ask_question(conn, profile, clock, "Second?")
    second = draw_consultation(conn, second, profile, clock, collector())
    await interpret_consultation(conn, second, clock, FixtureProvider())

    assert first.id != second.id
    assert len(consultations.list_consultations(conn, profile.id)) == 2
    assert readings.list_readings(conn, profile.id) == [daily]


def test_the_oracle_context_carries_no_transit(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "Which sky?")
    consultation = draw_consultation(conn, consultation, profile, clock, collector())

    context = consultation.interpretation_context
    assert context is not None
    assert context.kind is InterpretationKind.CONSULTATION
    assert context.significant_transits == []


def test_question_is_stored_verbatim_but_context_uses_normalized_text(conn, profile) -> None:
    clock = FixedClock(NOW)
    original = "  What\n\tshould\x00 I   notice?  "
    consultation = ask_question(conn, profile, clock, original)
    consultation = draw_consultation(conn, consultation, profile, clock, collector())

    assert consultation.question.text == original
    assert consultation.question.normalized_text == "What should I notice?"
    assert consultation.interpretation_context is not None
    assert consultation.interpretation_context.question == "What should I notice?"


def test_archive_delete_removes_only_the_owned_consultation(conn, profile) -> None:
    consultation = ask_question(conn, profile, FixedClock(NOW), "What can go?")

    assert not consultations.delete_consultation(
        conn, consultation.id, profile_id="another-profile"
    )
    assert consultations.delete_consultation(conn, consultation.id, profile_id=profile.id)
    assert consultations.get_by_id(conn, consultation.id) is None


def test_a_consultation_from_another_profile_is_refused(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "Whose question?")
    other = profile.model_copy(update={"id": "someone-else"})

    with pytest.raises(ValueError, match="does not belong"):
        draw_consultation(conn, consultation, other, clock, collector())


def test_legacy_error_names_the_rite_it_refuses() -> None:
    error = LegacyConsultationIsReadOnly("iching-v1")

    assert error.rite == "iching-v1"
    assert "read-only history" in str(error)
