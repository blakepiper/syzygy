"""Entropy collection for the Wheel.

docs/old/DESIGN.md section 7.2 requires that production draws combine OS
cryptographic randomness, high-resolution interaction timing, and a
session nonce - and that the result never depends solely on user key
timing. This module implements the mixing; `syzygy.sortes.draw` turns the
resulting digest into an unbiased card index.

The literal event sequence is never persisted (docs/old/DESIGN.md section 7.2) -
only the final digest (as `entropy_digest` on `TarotDraw`) leaves this
module.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

ENTROPY_ALGORITHM_VERSION = "entropy-v1"

#: Injected for tests only. Production code must never pass a fixed
#: byte source here - see `syzygy.sortes.draw.draw_card`'s docstring for
#: why that would be a hidden reroll/predictability path.
OsRandom = Callable[[int], bytes]


@dataclass(frozen=True)
class EntropyEvent:
    """One user-interaction sample (a keypress, a wheel impulse, ...).

    `kind` is a short free-text label (e.g. "impulse", "disturbance",
    "release") - never the actual key pressed, so this stays safe to log
    if ever needed without leaking input content.
    """

    monotonic_ns: int
    kind: str


@dataclass
class EntropyCollector:
    """Accumulates entropy for exactly one draw.

    Construct one instance per draw attempt. OS randomness is drawn fresh
    at `digest()` time (not just at construction), so calling `digest()`
    twice on the same collector deliberately yields different results -
    callers that need a stable draw must call `digest()` exactly once and
    reuse the value, which `syzygy.sortes.draw.draw_card` does.
    """

    session_nonce: bytes = field(default_factory=lambda: os.urandom(32))
    os_random: OsRandom = os.urandom
    _events: list[EntropyEvent] = field(default_factory=list)

    def record(self, kind: str, monotonic_ns: int | None = None) -> None:
        """Record one interaction sample. Safe to call zero times - OS
        randomness alone is still mixed into the digest.
        """
        self._events.append(
            EntropyEvent(
                monotonic_ns=monotonic_ns if monotonic_ns is not None else time.monotonic_ns(),
                kind=kind,
            )
        )

    @property
    def event_count(self) -> int:
        return len(self._events)

    def digest(self) -> bytes:
        """Mix OS randomness + session nonce + recorded events into a
        32-byte digest. Deterministic given a fixed `os_random` and a
        fixed event list (this is how tests get reproducibility - see
        `tests/sortes/test_entropy.py`).
        """
        hasher = hashlib.blake2b(digest_size=32, person=ENTROPY_ALGORITHM_VERSION.encode()[:16])
        hasher.update(self.os_random(32))
        hasher.update(self.session_nonce)
        hasher.update(len(self._events).to_bytes(4, "big"))
        for event in self._events:
            hasher.update(event.kind.encode("utf-8"))
            hasher.update(event.monotonic_ns.to_bytes(8, "big", signed=True))
        return hasher.digest()
