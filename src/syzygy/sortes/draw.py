"""Unbiased card selection from an entropy digest.

DESIGN.md section 7.3 requires either a standard `randbelow`-style
implementation or rejection sampling, explicitly ruling out naive modulo
arithmetic over an unconstrained byte range (which would bias results
towards low card indices, since 256 is not a multiple of 78). This module
implements rejection sampling by hand rather than reseeding
`random`/`secrets`, because the whole point is to select deterministically
*from a specific digest* (so a fixed test digest reproduces a fixed card) -
reseeding a global PRNG would not give us that.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from syzygy.domain.tarot import TarotDraw
from syzygy.sortes.deck import load_deck
from syzygy.sortes.entropy import EntropyCollector

SORTES_ALGORITHM_VERSION = "sortes-v1"


def unbiased_index(digest: bytes, upper_bound: int) -> int:
    """Rejection-sample an unbiased index in `[0, upper_bound)` from
    `digest`. If `digest` is exhausted without producing an unrejected
    byte (astronomically unlikely for a 32-byte digest and
    `upper_bound=78`, but possible in principle), deterministically
    extends it by re-hashing - so this always terminates and always stays
    a pure function of the input digest.
    """
    if upper_bound <= 0 or upper_bound > 256:
        raise ValueError(f"upper_bound must be in (0, 256], got {upper_bound}")

    # Largest multiple of upper_bound that fits in a byte. Bytes >= this
    # threshold are rejected to avoid modulo bias.
    threshold = (256 // upper_bound) * upper_bound

    extension = 0
    while True:
        chunk = digest if extension == 0 else hashlib.blake2b(
            digest + extension.to_bytes(4, "big"), digest_size=32
        ).digest()
        for byte in chunk:
            if byte < threshold:
                return byte % upper_bound
        extension += 1


def draw_card(collector: EntropyCollector, *, now: datetime) -> TarotDraw:
    """Perform one Sortes draw: derive an entropy digest from `collector`,
    select an unbiased index across the full 78-card deck, and return the
    resulting immutable `TarotDraw`.

    Callers are responsible for persisting the returned `TarotDraw`
    immediately (DESIGN.md section 7.4) - this function has no side
    effects of its own and does not touch storage.

    `now` is required, not defaulted to `datetime.now()` - `syzygy.clock`
    is the single source of "now" everywhere in this codebase (see
    AGENTS.md); callers pass `clock.now_utc()`.

    `collector.os_random` must be `os.urandom` (the default) in production.
    Only test code should construct an `EntropyCollector` with a fixed
    `os_random` - see `tests/sortes/test_draw.py` for the pattern. There is
    deliberately no CLI flag or config option that lets a fixed source
    reach this function in a normal run.
    """
    deck = load_deck()
    digest = collector.digest()
    index = unbiased_index(digest, upper_bound=len(deck))
    card = deck[index]
    drawn_at = now
    return TarotDraw(
        card_id=card.id,
        drawn_at_utc=drawn_at,
        sortes_version=SORTES_ALGORITHM_VERSION,
        entropy_digest=digest.hex(),
    )
