"""Unbiased three-coin I Ching casting over shared interaction entropy."""

from __future__ import annotations

import hashlib
from datetime import datetime

from syzygy.domain.iching import IChingCast, IChingLineValue, LinePolarity
from syzygy.iching.book import number_for_lines
from syzygy.sortes.draw import unbiased_index
from syzygy.sortes.entropy import EntropyCollector

CAST_METHOD_VERSION = "three-coin-v1"


def line_value_for_pattern(pattern: int) -> IChingLineValue:
    """Map one of eight equiprobable three-coin patterns to its line."""
    if not 0 <= pattern < 8:
        raise ValueError("coin pattern must be in [0, 8)")
    return IChingLineValue(6 + pattern.bit_count())


def cast_hexagram(collector: EntropyCollector, *, now: datetime) -> IChingCast:
    """Cast six bottom-up lines from one mixed digest and commit-ready facts."""
    digest = collector.digest()
    lines: list[IChingLineValue] = []
    for line_index in range(6):
        line_digest = hashlib.blake2b(
            digest + line_index.to_bytes(1, "big"),
            digest_size=32,
            person=b"syzygy-i-ching",
        ).digest()
        lines.append(line_value_for_pattern(unbiased_index(line_digest, 8)))

    primary_lines = [line.polarity for line in lines]
    resulting_lines = [
        (
            LinePolarity.YIN
            if line is IChingLineValue.OLD_YANG
            else LinePolarity.YANG
            if line is IChingLineValue.OLD_YIN
            else line.polarity
        )
        for line in lines
    ]
    return IChingCast(
        lines=lines,
        primary_hexagram_number=number_for_lines(primary_lines),
        changing_lines=[index for index, line in enumerate(lines, start=1) if line.is_changing],
        resulting_hexagram_number=number_for_lines(resulting_lines),
        cast_at_utc=now,
        method_version=CAST_METHOD_VERSION,
        entropy_digest=digest.hex(),
    )
