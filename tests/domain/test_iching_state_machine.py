from syzygy.domain.iching_consultation import ALLOWED_TRANSITIONS, IChingStatus


def test_every_unlisted_iching_transition_is_illegal() -> None:
    for current in IChingStatus:
        for requested in IChingStatus:
            allowed = requested in ALLOWED_TRANSITIONS[current]
            expected = (current, requested) in {
                (IChingStatus.ASKED, IChingStatus.CAST),
                (IChingStatus.CAST, IChingStatus.CONTEXT_READY),
                (IChingStatus.CONTEXT_READY, IChingStatus.INTERPRETING),
                (IChingStatus.INTERPRETING, IChingStatus.COMPLETE),
                (IChingStatus.INTERPRETING, IChingStatus.INTERPRETATION_FAILED),
                (IChingStatus.INTERPRETATION_FAILED, IChingStatus.INTERPRETING),
            }
            assert allowed is expected
