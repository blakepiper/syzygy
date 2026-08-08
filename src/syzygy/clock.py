"""Centralized time access.

DESIGN.md section 10 and ARCHITECTURE_HANDOFF.md section 29 both require a
single, injectable source of "now" so that daily-reading logic and tests
never call `datetime.now()` directly. Every subsystem that needs the
current time should take a `Clock` rather than importing `datetime` and
calling `.now()` itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Returns the current instant. Implementations decide the timezone."""

    def now_utc(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """Production clock backed by the operating system."""

    def now_utc(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock for tests and `--at` debug overrides.

    Never wired into production code paths by default - only construct
    this explicitly (e.g. from a CLI `--at` flag or a test fixture).
    """

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._instant = instant.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._instant
