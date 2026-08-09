from syzygy.sortes.entropy import EntropyCollector


def _fixed_os_random(n: int) -> bytes:
    return b"\x42" * n


def test_digest_is_deterministic_given_fixed_os_random_and_events():
    a = EntropyCollector(session_nonce=b"nonce", os_random=_fixed_os_random)
    a.record("impulse", monotonic_ns=1000)
    a.record("release", monotonic_ns=2000)

    b = EntropyCollector(session_nonce=b"nonce", os_random=_fixed_os_random)
    b.record("impulse", monotonic_ns=1000)
    b.record("release", monotonic_ns=2000)

    assert a.digest() == b.digest()


def test_digest_changes_when_an_event_changes():
    a = EntropyCollector(session_nonce=b"nonce", os_random=_fixed_os_random)
    a.record("impulse", monotonic_ns=1000)

    b = EntropyCollector(session_nonce=b"nonce", os_random=_fixed_os_random)
    b.record("impulse", monotonic_ns=1001)  # one nanosecond different

    assert a.digest() != b.digest()


def test_digest_changes_when_session_nonce_changes():
    a = EntropyCollector(session_nonce=b"nonce-a", os_random=_fixed_os_random)
    b = EntropyCollector(session_nonce=b"nonce-b", os_random=_fixed_os_random)
    assert a.digest() != b.digest()


def test_zero_events_still_produces_a_digest():
    # OS randomness alone must be sufficient - the wheel is a real
    # entropy contribution, not a required one (docs/old/DESIGN.md 7.2).
    collector = EntropyCollector(session_nonce=b"nonce", os_random=_fixed_os_random)
    assert collector.event_count == 0
    digest = collector.digest()
    assert len(digest) == 32


def test_production_default_uses_os_urandom():
    import os

    collector = EntropyCollector()
    assert collector.os_random is os.urandom
