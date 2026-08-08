from datetime import UTC, datetime, timezone

import pytest

from syzygy.clock import FixedClock, SystemClock


def test_system_clock_returns_timezone_aware_utc():
    clock = SystemClock()
    now = clock.now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_fixed_clock_returns_the_fixed_instant():
    instant = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    clock = FixedClock(instant)
    assert clock.now_utc() == instant


def test_fixed_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 8, 7, 12, 0))


def test_fixed_clock_normalizes_to_utc():
    from datetime import timedelta

    eastern = timezone(timedelta(hours=-4))
    instant = datetime(2026, 8, 7, 8, 0, tzinfo=eastern)
    clock = FixedClock(instant)
    assert clock.now_utc() == instant.astimezone(UTC)
