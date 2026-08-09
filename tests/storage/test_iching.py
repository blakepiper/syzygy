from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.clock import FixedClock
from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement, TransitSnapshot
from syzygy.domain.iching_consultation import IChingStatus
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.profile import Profile
from syzygy.iching.cast import cast_hexagram
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import iching, oracle, readings
from syzygy.storage.database import connect
from syzygy.storage.iching_service import ask_question, cast_consultation, interpret_iching
from syzygy.storage.migrations import apply_all
from syzygy.storage.oracle_service import ask_question as ask_thoth_question
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

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise RuntimeError("no interpreter")


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "iching.db")
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
        id="iching-profile",
        display_name="Blake",
        birth_data=birth,
        natal_chart=chart,
        created_at_utc=NOW,
        updated_at_utc=NOW,
    )
    insert_profile(conn, value)
    return value


def collector(seed: int = 1) -> EntropyCollector:
    return EntropyCollector(session_nonce=b"iching", os_random=lambda n: bytes([seed]) * n)


@pytest.mark.asyncio
async def test_failed_interpretation_retry_reuses_committed_cast(conn, profile) -> None:
    clock = FixedClock(NOW)
    consultation = ask_question(conn, profile, clock, "What is changing?")
    consultation = cast_consultation(
        conn, consultation, profile, clock, Astrology(), collector()
    )
    original_cast = consultation.cast

    failed = await interpret_iching(conn, consultation, clock, FailingProvider())
    retried = await interpret_iching(conn, failed, clock, FixtureProvider())

    assert failed.status is IChingStatus.INTERPRETATION_FAILED
    assert failed.prompt_version == "iching-v1"
    assert retried.status is IChingStatus.COMPLETE
    assert retried.cast == original_cast
    assert retried.result is not None
    assert retried.result.prompt_version == "iching-v1"


def test_crash_after_cast_resumes_without_using_entropy_again(conn, profile) -> None:
    clock = FixedClock(NOW)
    asked = ask_question(conn, profile, clock, "What remains fixed?")
    committed = iching.commit_cast(
        conn, asked.id, cast_hexagram(collector(), now=NOW)
    )
    hostile = EntropyCollector(
        os_random=lambda _n: (_ for _ in ()).throw(AssertionError("cast again"))
    )

    resumed = cast_consultation(conn, committed, profile, clock, Astrology(), hostile)

    assert resumed.status is IChingStatus.CONTEXT_READY
    assert resumed.cast == committed.cast


def test_iching_is_separate_from_thoth_oracle_and_daily_reading(conn, profile) -> None:
    clock = FixedClock(NOW)
    i_ching = ask_question(conn, profile, clock, "I Ching?")
    thoth = ask_thoth_question(conn, profile, clock, "Thoth?")
    daily = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=NOW.date().isoformat(),
        consultation_local_timestamp=NOW.isoformat(),
        consultation_utc_timestamp=NOW,
        consultation_timezone="UTC",
    )

    assert iching.list_consultations(conn, profile.id) == [i_ching]
    assert oracle.list_consultations(conn, profile.id) == [thoth]
    assert readings.list_readings(conn, profile.id) == [daily]


def test_archive_delete_removes_only_the_owned_iching_consultation(conn, profile) -> None:
    consultation = ask_question(conn, profile, FixedClock(NOW), "What can go?")

    assert not iching.delete_consultation(
        conn, consultation.id, profile_id="another-profile"
    )
    assert iching.delete_consultation(conn, consultation.id, profile_id=profile.id)
    assert iching.get_by_id(conn, consultation.id) is None
