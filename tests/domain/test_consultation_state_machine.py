from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from syzygy.domain.consultation import (
    ALLOWED_TRANSITIONS,
    Consultation,
    ConsultationStatus,
)
from syzygy.domain.iching import IChingCast, IChingLineValue
from syzygy.domain.oracle import OracleQuestion
from syzygy.domain.tarot import TarotDraw

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)

QUESTION = OracleQuestion(
    text="What am I standing in?",
    normalized_text="What am I standing in?",
    asked_at_utc=NOW,
    consultation_local_date="2026-08-09",
)

DRAW = TarotDraw(
    card_id="major-00-the-fool",
    drawn_at_utc=NOW,
    sortes_version="sortes-v1",
    entropy_digest="00" * 32,
)

CAST = IChingCast(
    lines=[IChingLineValue.YOUNG_YANG] * 6,
    primary_hexagram_number=1,
    changing_lines=[],
    resulting_hexagram_number=1,
    cast_at_utc=NOW,
    method_version="three-coin-v1",
    entropy_digest="00" * 32,
)


def consultation(**overrides) -> Consultation:
    payload = {
        "id": "c1",
        "profile_id": "p1",
        "question": QUESTION,
        "status": ConsultationStatus.DRAWN,
        "consultation_local_timestamp": NOW.isoformat(),
        "consultation_timezone": "UTC",
        "card_draw": DRAW,
        "cast": CAST,
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
    }
    payload.update(overrides)
    return Consultation(**payload)


def test_every_unlisted_transition_is_illegal() -> None:
    statuses = set(ConsultationStatus)
    for current in ConsultationStatus:
        legal = ALLOWED_TRANSITIONS[current]
        assert legal <= statuses
        for requested in ConsultationStatus:
            assert (requested in legal) is (
                (current, requested)
                in {
                    (ConsultationStatus.ASKED, ConsultationStatus.DRAWN),
                    (ConsultationStatus.DRAWN, ConsultationStatus.CONTEXT_READY),
                    (ConsultationStatus.CONTEXT_READY, ConsultationStatus.INTERPRETING),
                    (ConsultationStatus.INTERPRETING, ConsultationStatus.COMPLETE),
                    (
                        ConsultationStatus.INTERPRETING,
                        ConsultationStatus.INTERPRETATION_FAILED,
                    ),
                    (
                        ConsultationStatus.INTERPRETATION_FAILED,
                        ConsultationStatus.INTERPRETING,
                    ),
                }
            )


def test_no_state_after_the_wheel_can_return_to_asked_or_drawn() -> None:
    for current in ConsultationStatus:
        if current is ConsultationStatus.ASKED:
            continue
        assert ConsultationStatus.ASKED not in ALLOWED_TRANSITIONS[current]
        assert ConsultationStatus.DRAWN not in ALLOWED_TRANSITIONS[current]


def test_a_complete_consultation_is_terminal() -> None:
    assert ALLOWED_TRANSITIONS[ConsultationStatus.COMPLETE] == frozenset()


@pytest.mark.parametrize(
    "status",
    [status for status in ConsultationStatus if status is not ConsultationStatus.ASKED],
)
@pytest.mark.parametrize("absent", ["card_draw", "cast"])
def test_a_one_object_consultation_cannot_be_constructed(status, absent) -> None:
    with pytest.raises(ValidationError, match="both a card and a cast"):
        consultation(status=status, **{absent: None})


def test_an_unasked_consultation_carries_neither_object() -> None:
    assert consultation(
        status=ConsultationStatus.ASKED, card_draw=None, cast=None
    ).card_draw is None
    with pytest.raises(ValidationError, match="neither chance object"):
        consultation(status=ConsultationStatus.ASKED, cast=None)
