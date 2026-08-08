from syzygy.astrology.policy import TransitAspectPolicy
from syzygy.domain.astrology import TransitAspect

POLICY = TransitAspectPolicy()


def _aspect(**overrides) -> TransitAspect:
    defaults = dict(
        transiting_body="Jupiter",
        natal_target="Venus",
        aspect="conjunction",
        orb_degrees=1.0,
        movement="applying",
    )
    defaults.update(overrides)
    return TransitAspect(**defaults)


def test_conjunction_at_2_99_degrees_passes():
    assert POLICY.passes(_aspect(aspect="conjunction", orb_degrees=2.99))


def test_conjunction_at_3_01_degrees_fails():
    assert not POLICY.passes(_aspect(aspect="conjunction", orb_degrees=3.01))


def test_sextile_at_2_00_degrees_passes():
    assert POLICY.passes(_aspect(aspect="sextile", orb_degrees=2.00))


def test_sextile_at_2_01_degrees_fails():
    assert not POLICY.passes(_aspect(aspect="sextile", orb_degrees=2.01))


def test_transiting_moon_aspect_at_1_49_degrees_passes():
    assert POLICY.passes(_aspect(transiting_body="Moon", aspect="trine", orb_degrees=1.49))


def test_transiting_moon_aspect_at_1_51_degrees_fails():
    # Would pass the base 3.0 degree trine cap, but the Moon-specific
    # 1.5 degree cap must override it (DESIGN.md 9.4).
    assert not POLICY.passes(_aspect(transiting_body="Moon", aspect="trine", orb_degrees=1.51))


def test_natal_ascendant_target_applies_2_0_degree_cap():
    # Would pass the base 3.0 degree conjunction cap, but the natal-angle
    # 2.0 degree cap must override it.
    assert POLICY.passes(_aspect(natal_target="Ascendant", aspect="conjunction", orb_degrees=2.0))
    assert not POLICY.passes(
        _aspect(natal_target="Ascendant", aspect="conjunction", orb_degrees=2.01)
    )


def test_natal_midheaven_target_applies_2_0_degree_cap():
    assert not POLICY.passes(
        _aspect(natal_target="Midheaven", aspect="trine", orb_degrees=2.5)
    )


def test_quintile_is_never_a_candidate_regardless_of_orb():
    assert not POLICY.passes(_aspect(aspect="quintile", orb_degrees=0.01))


def test_filter_preserves_order_and_drops_failures():
    aspects = [
        _aspect(aspect="conjunction", orb_degrees=1.0),
        _aspect(aspect="conjunction", orb_degrees=5.0),  # fails
        _aspect(aspect="trine", orb_degrees=2.0),
    ]
    result = POLICY.filter(aspects)
    assert result == [aspects[0], aspects[2]]


def test_policy_version_is_stable_string():
    assert POLICY.version == "transit-policy-v1"
