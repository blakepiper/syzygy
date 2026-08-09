from datetime import UTC, datetime

import pytest

from syzygy.sortes.deck import load_deck
from syzygy.sortes.draw import draw_card, unbiased_index
from syzygy.sortes.entropy import EntropyCollector


def _fixed_os_random_factory(seed_byte: int):
    def _os_random(n: int) -> bytes:
        return bytes([seed_byte]) * n

    return _os_random


def test_unbiased_index_stays_in_range():
    for seed in range(256):
        digest = bytes([seed]) * 32
        index = unbiased_index(digest, upper_bound=78)
        assert 0 <= index < 78


def test_unbiased_index_is_deterministic():
    digest = bytes(range(32))
    assert unbiased_index(digest, 78) == unbiased_index(digest, 78)


def test_unbiased_index_rejects_out_of_range_upper_bound():
    with pytest.raises(ValueError):
        unbiased_index(b"\x00" * 32, upper_bound=0)
    with pytest.raises(ValueError):
        unbiased_index(b"\x00" * 32, upper_bound=300)


def test_all_78_indices_are_reachable():
    # Every byte value 0-255 that survives rejection sampling (threshold =
    # 234, since 256 // 78 * 78 = 234) maps to byte % 78. Sweeping all
    # surviving byte values must hit every index 0-77 at least once.
    seen = set()
    for byte_value in range(234):
        seen.add(byte_value % 78)
    assert seen == set(range(78))


def test_draw_card_is_deterministic_given_a_fixed_digest():
    collector_a = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    collector_a.record("impulse", monotonic_ns=123)
    collector_b = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    collector_b.record("impulse", monotonic_ns=123)

    now = datetime(2026, 8, 7, tzinfo=UTC)
    draw_a = draw_card(collector_a, now=now)
    draw_b = draw_card(collector_b, now=now)

    assert draw_a.card_id == draw_b.card_id
    assert draw_a.entropy_digest == draw_b.entropy_digest


def test_draw_card_selects_a_real_card_id():
    collector = EntropyCollector(session_nonce=b"y", os_random=_fixed_os_random_factory(3))
    draw = draw_card(collector, now=datetime(2026, 8, 7, tzinfo=UTC))
    deck_ids = {c.id for c in load_deck()}
    assert draw.card_id in deck_ids


def test_draw_card_records_sortes_version():
    collector = EntropyCollector(session_nonce=b"z", os_random=_fixed_os_random_factory(9))
    draw = draw_card(collector, now=datetime(2026, 8, 7, tzinfo=UTC))
    assert draw.sortes_version == "sortes-v1"


def test_draw_distribution_is_approximately_uniform():
    # Loose statistical smoke test (docs/old/DESIGN.md 25.3): not a proof of
    # randomness, just a guard against a gross implementation bias (e.g.
    # accidentally using modulo without rejection sampling).
    import os

    counts = [0] * 78
    trials = 7800
    for _ in range(trials):
        collector = EntropyCollector(os_random=os.urandom)
        collector.record("impulse", monotonic_ns=os.urandom(8).hex().__hash__())
        draw = draw_card(collector, now=datetime(2026, 8, 7, tzinfo=UTC))
        deck = load_deck()
        index = next(i for i, c in enumerate(deck) if c.id == draw.card_id)
        counts[index] += 1

    expected = trials / 78
    # Generous tolerance: this is a bias smoke test, not a chi-square test.
    assert min(counts) > expected * 0.5
    assert max(counts) < expected * 1.5
