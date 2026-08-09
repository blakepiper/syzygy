import hashlib
from datetime import UTC, datetime

from syzygy.domain.iching import IChingLineValue
from syzygy.iching.cast import CAST_METHOD_VERSION, cast_hexagram, line_value_for_pattern
from syzygy.sortes.draw import unbiased_index
from syzygy.sortes.entropy import EntropyCollector

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


def test_three_coin_patterns_have_the_exact_decided_probabilities() -> None:
    outcomes = [line_value_for_pattern(pattern) for pattern in range(8)]

    assert outcomes.count(IChingLineValue.OLD_YIN) == 1
    assert outcomes.count(IChingLineValue.YOUNG_YANG) == 3
    assert outcomes.count(IChingLineValue.YOUNG_YIN) == 3
    assert outcomes.count(IChingLineValue.OLD_YANG) == 1


def test_large_seeded_sample_tracks_the_three_coin_distribution() -> None:
    counts = {line: 0 for line in IChingLineValue}
    trials = 80_000
    for seed in range(trials):
        digest = hashlib.blake2b(seed.to_bytes(8, "big"), digest_size=32).digest()
        counts[line_value_for_pattern(unbiased_index(digest, 8))] += 1

    expected = {
        IChingLineValue.OLD_YIN: 1 / 8,
        IChingLineValue.YOUNG_YANG: 3 / 8,
        IChingLineValue.YOUNG_YIN: 3 / 8,
        IChingLineValue.OLD_YANG: 1 / 8,
    }
    for line, probability in expected.items():
        assert abs(counts[line] / trials - probability) < 0.01


def test_cast_is_deterministic_for_fixed_entropy_and_records_all_fixed_facts() -> None:
    def collector() -> EntropyCollector:
        return EntropyCollector(session_nonce=b"i-ching", os_random=lambda n: b"\x19" * n)

    first = cast_hexagram(collector(), now=NOW)
    second = cast_hexagram(collector(), now=NOW)

    assert first == second
    assert len(first.lines) == 6
    assert first.method_version == CAST_METHOD_VERSION
    assert len(first.entropy_digest) == 64
    assert first.changing_lines == [
        index for index, line in enumerate(first.lines, start=1) if line.is_changing
    ]
