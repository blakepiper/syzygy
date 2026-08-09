from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.clock import FixedClock
from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement, TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.oracle import OracleStatus
from syzygy.domain.profile import Profile
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import oracle, readings
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.oracle_service import (
    ask_question,
    draw_oracle_consultation,
    interpret_oracle,
)
from syzygy.storage.profiles import insert_profile

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


class Astrology:
    def calculate_natal(self, birth: BirthData) -> NatalChart:
        raise AssertionError

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=[],
            raw_aspects=[],
            astrology_policy_version=POLICY_VERSION,
        )


class FailingProvider:
    provider_id = "failure"
    model_id = "failure-v1"

    async def interpret(
        self, context: InterpretationContext
    ) -> InterpretationResult:
        raise RuntimeError("no interpreter")


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
        placements=[
            NatalPlacement(body="Sun", sign="Aries", longitude=1),
            NatalPlacement(body="Moon", sign="Taurus", longitude=31),
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


@pytest.mark.asyncio
async def test_failure_retry_reuses_the_committed_card(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What needs my attention?")
    consultation = draw_oracle_consultation(
        conn, consultation, profile, clock, Astrology(), collector()
    )
    original_draw = consultation.card_draw

    failed = await interpret_oracle(conn, consultation, clock, FailingProvider())
    retried = await interpret_oracle(conn, failed, clock, FixtureProvider())

    assert failed.status is OracleStatus.INTERPRETATION_FAILED
    assert failed.provider_id == "failure"
    assert failed.model_id == "failure-v1"
    assert failed.prompt_version == "oracle-v1"
    assert retried.status is OracleStatus.COMPLETE
    assert retried.card_draw == original_draw
    assert retried.result is not None
    assert retried.provider_id == "fixture"
    assert retried.model_id == FixtureProvider.model_id
    assert retried.prompt_version == retried.result.prompt_version


def test_crash_after_draw_resumes_without_using_entropy_again(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What remains fixed?")
    committed = oracle.commit_draw(conn, consultation.id, draw_card(collector(), now=NOW))
    assert committed.card_draw is not None

    resumed = draw_oracle_consultation(
        conn,
        committed,
        profile,
        clock,
        Astrology(),
        EntropyCollector(os_random=lambda _n: (_ for _ in ()).throw(AssertionError("redraw"))),
    )

    assert resumed.status is OracleStatus.CONTEXT_READY
    assert resumed.card_draw == committed.card_draw


def test_many_consultations_do_not_touch_or_block_daily_readings(conn, profile) -> None:
    clock = FixedClock(NOW)
    first = ask_question(conn, profile, clock, "First?")
    second = ask_question(conn, profile, clock, "Second?")
    daily = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=NOW.date().isoformat(),
        consultation_local_timestamp=NOW.isoformat(),
        consultation_utc_timestamp=NOW,
        consultation_timezone="UTC",
    )

    assert first.id != second.id
    assert len(oracle.list_consultations(conn, profile.id)) == 2
    assert readings.list_readings(conn, profile.id) == [daily]


def test_question_is_stored_verbatim_but_context_uses_normalized_text(conn, profile) -> None:
    clock = FixedClock(NOW)
    original = "  What\n\tshould\x00 I   notice?  "
    consultation = ask_question(conn, profile, clock, original)
    consultation = draw_oracle_consultation(
        conn, consultation, profile, clock, Astrology(), collector()
    )

    assert consultation.question.text == original
    assert consultation.question.normalized_text == "What should I notice?"
    assert consultation.interpretation_context is not None
    assert consultation.interpretation_context.question == "What should I notice?"
