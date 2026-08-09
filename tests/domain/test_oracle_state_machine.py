from __future__ import annotations

from syzygy.domain.oracle import ALLOWED_TRANSITIONS, OracleStatus


def test_every_unlisted_oracle_transition_is_illegal() -> None:
    statuses = set(OracleStatus)
    for current in OracleStatus:
        legal = ALLOWED_TRANSITIONS[current]
        assert legal <= statuses
        for requested in OracleStatus:
            assert (requested in legal) is (
                (current, requested)
                in {
                    (OracleStatus.ASKED, OracleStatus.DRAWN),
                    (OracleStatus.DRAWN, OracleStatus.CONTEXT_READY),
                    (OracleStatus.CONTEXT_READY, OracleStatus.INTERPRETING),
                    (OracleStatus.INTERPRETING, OracleStatus.COMPLETE),
                    (OracleStatus.INTERPRETING, OracleStatus.INTERPRETATION_FAILED),
                    (OracleStatus.INTERPRETATION_FAILED, OracleStatus.INTERPRETING),
                }
            )


def test_no_state_after_a_draw_can_return_to_asked_or_drawn() -> None:
    for current in OracleStatus:
        if current is OracleStatus.ASKED:
            continue
        assert OracleStatus.ASKED not in ALLOWED_TRANSITIONS[current]
        assert OracleStatus.DRAWN not in ALLOWED_TRANSITIONS[current]

