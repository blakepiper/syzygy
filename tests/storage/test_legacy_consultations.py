"""The two superseded rites: readable forever, writable never (M22.1d).

There is deliberately no code path that creates an `oracle-v1` or
`iching-v1` row any more, so these tests insert them the only way that is
left - as the historical database rows they are - and then assert that
Syzygy can still read them and cannot advance them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.clock import FixedClock
from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement
from syzygy.domain.iching_consultation import IChingConsultation, IChingStatus
from syzygy.domain.oracle import OracleConsultation, OracleStatus
from syzygy.domain.profile import Profile
from syzygy.iching.cast import cast_hexagram
from syzygy.interpretation.prompts import interpretation_contract
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import consultations, iching, oracle
from syzygy.storage.consultation_service import (
    draw_consultation,
    interpret_consultation,
    refuse_legacy,
)
from syzygy.storage.consultations import LegacyConsultationIsReadOnly
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "legacy.db")
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
    value = Profile(
        id="legacy-profile",
        display_name="Blake",
        birth_data=birth,
        natal_chart=NatalChart(
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
        ),
        created_at_utc=NOW,
        updated_at_utc=NOW,
    )
    insert_profile(conn, value)
    return value


def _collector() -> EntropyCollector:
    return EntropyCollector(session_nonce=b"legacy", os_random=lambda n: b"\x07" * n)


def insert_legacy_oracle_row(conn, profile_id: str, consultation_id: str = "legacy-thoth"):
    conn.execute(
        """
        INSERT INTO oracle_consultations (
            id, profile_id, question_text, question_normalized, asked_at_utc,
            consultation_local_date, consultation_local_timestamp,
            consultation_timezone, status, card_draw_json, prompt_version,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            consultation_id,
            profile_id,
            "What did the old rite ask?",
            "What did the old rite ask?",
            NOW.isoformat(),
            "2026-08-09",
            NOW.isoformat(),
            "UTC",
            OracleStatus.DRAWN.value,
            draw_card(_collector(), now=NOW).model_dump_json(),
            "oracle-v1",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    return consultation_id


def insert_legacy_iching_row(conn, profile_id: str, consultation_id: str = "legacy-iching"):
    conn.execute(
        """
        INSERT INTO iching_consultations (
            id, profile_id, question_text, question_normalized, asked_at_utc,
            consultation_local_date, consultation_local_timestamp,
            consultation_timezone, status, cast_json, prompt_version,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            consultation_id,
            profile_id,
            "What was changing then?",
            "What was changing then?",
            NOW.isoformat(),
            "2026-08-09",
            NOW.isoformat(),
            "UTC",
            IChingStatus.CAST.value,
            cast_hexagram(_collector(), now=NOW).model_dump_json(),
            "iching-v1",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    return consultation_id


def test_legacy_rows_still_read(conn, profile) -> None:
    thoth_id = insert_legacy_oracle_row(conn, profile.id)
    iching_id = insert_legacy_iching_row(conn, profile.id)

    thoth = oracle.get_by_id(conn, thoth_id)
    cast = iching.get_by_id(conn, iching_id)

    assert thoth is not None and thoth.card_draw is not None
    assert thoth.prompt_version == "oracle-v1"
    assert cast is not None and cast.cast is not None
    assert cast.prompt_version == "iching-v1"
    assert oracle.list_consultations(conn, profile.id) == [thoth]
    assert iching.list_consultations(conn, profile.id) == [cast]
    # They are a separate archive kind, not consultations of the new rite.
    assert consultations.list_consultations(conn, profile.id) == []


@pytest.mark.parametrize("module", [oracle, iching])
def test_the_legacy_modules_have_no_writers_left(module) -> None:
    for name in (
        "create_asked",
        "commit_draw",
        "commit_cast",
        "commit_context",
        "begin_interpreting",
        "complete_interpretation",
        "fail_interpretation",
        "_advance",
    ):
        assert not hasattr(module, name), f"{module.__name__}.{name} can still write"


def test_the_service_layer_refuses_to_advance_a_legacy_row(conn, profile) -> None:
    insert_legacy_oracle_row(conn, profile.id)
    insert_legacy_iching_row(conn, profile.id)
    thoth = oracle.get_by_id(conn, "legacy-thoth")
    cast = iching.get_by_id(conn, "legacy-iching")
    clock = FixedClock(NOW)

    for record in (thoth, cast):
        with pytest.raises(LegacyConsultationIsReadOnly):
            draw_consultation(conn, record, profile, clock, _collector())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_legacy_row_cannot_be_interpreted_again(conn, profile) -> None:
    insert_legacy_oracle_row(conn, profile.id)
    thoth = oracle.get_by_id(conn, "legacy-thoth")

    with pytest.raises(LegacyConsultationIsReadOnly):
        await interpret_consultation(
            conn,
            thoth,  # type: ignore[arg-type]
            FixedClock(NOW),
            None,  # type: ignore[arg-type]
        )


def test_refuse_legacy_passes_anything_that_is_not_a_legacy_record() -> None:
    assert refuse_legacy(None) is None
    assert refuse_legacy("not a consultation") is None


@pytest.mark.parametrize("kind", ["oracle", "i_ching"])
def test_a_stored_legacy_context_can_never_produce_a_prompt_again(kind) -> None:
    """`oracle-v1`/`iching-v1` prompt text is gone; the kinds still parse."""
    from syzygy.domain.interpretation import InterpretationKind

    class _StoredContext:
        pass

    context = _StoredContext()
    context.kind = InterpretationKind(kind)  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="read-only history"):
        interpretation_contract(context)  # type: ignore[arg-type]


def test_the_retired_prompts_are_gone() -> None:
    import syzygy.interpretation.prompts as prompts

    assert not hasattr(prompts, "ORACLE_SYSTEM_PROMPT")
    assert not hasattr(prompts, "ICHING_SYSTEM_PROMPT")
    assert not hasattr(prompts, "ICHING_PROMPT_VERSION")
    assert not hasattr(prompts, "build_oracle_prompt")
    assert not hasattr(prompts, "build_iching_prompt")


def test_legacy_records_are_still_deletable_from_the_archive(conn, profile) -> None:
    insert_legacy_oracle_row(conn, profile.id)
    insert_legacy_iching_row(conn, profile.id)

    assert oracle.delete_consultation(conn, "legacy-thoth", profile_id=profile.id)
    assert iching.delete_consultation(conn, "legacy-iching", profile_id=profile.id)
    assert oracle.get_by_id(conn, "legacy-thoth") is None
    assert iching.get_by_id(conn, "legacy-iching") is None


def test_legacy_domain_models_carry_no_transition_table() -> None:
    import syzygy.domain.iching_consultation as iching_domain
    import syzygy.domain.oracle as oracle_domain

    assert not hasattr(oracle_domain, "ALLOWED_TRANSITIONS")
    assert not hasattr(iching_domain, "ALLOWED_TRANSITIONS")
    # The aggregates themselves survive: the archive reads them.
    assert OracleConsultation is not None
    assert IChingConsultation is not None
