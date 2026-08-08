from syzygy.domain.reading import ALLOWED_TRANSITIONS, ReadingStatus


def test_complete_is_a_terminal_state():
    assert ALLOWED_TRANSITIONS[ReadingStatus.COMPLETE] == frozenset()


def test_prepared_can_only_advance_to_drawn():
    assert ALLOWED_TRANSITIONS[ReadingStatus.PREPARED] == frozenset({ReadingStatus.DRAWN})


def test_no_state_can_transition_back_to_prepared_or_drawn():
    # This is the "no hidden reroll" invariant at the type level: once a
    # card exists (status >= DRAWN), nothing in the state machine can walk
    # back to PREPARED or DRAWN.
    forbidden = {ReadingStatus.PREPARED, ReadingStatus.DRAWN}
    for state, allowed_targets in ALLOWED_TRANSITIONS.items():
        if state in (ReadingStatus.PREPARED,):
            continue  # PREPARED -> DRAWN is the one legitimate forward edge into DRAWN
        assert not (allowed_targets & forbidden), f"{state} can reach {forbidden}"


def test_interpretation_failed_can_retry_but_not_redraw():
    allowed = ALLOWED_TRANSITIONS[ReadingStatus.INTERPRETATION_FAILED]
    assert allowed == frozenset({ReadingStatus.INTERPRETING})


def test_every_status_has_a_transition_entry():
    for status in ReadingStatus:
        assert status in ALLOWED_TRANSITIONS
