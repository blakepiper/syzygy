from syzygy.astrology.ranking import TOP_N, TransitRanker
from syzygy.domain.astrology import TransitAspect

RANKER = TransitRanker()


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


def test_deterministic_ordering_given_fixed_input():
    aspects = [
        _aspect(transiting_body="Saturn", orb_degrees=2.5),
        _aspect(transiting_body="Sun", orb_degrees=0.2),
        _aspect(transiting_body="Mars", orb_degrees=1.5),
    ]
    result_a = [r.aspect.transiting_body for r in RANKER.rank(aspects)]
    result_b = [r.aspect.transiting_body for r in RANKER.rank(aspects)]
    assert result_a == result_b
    assert result_a == ["Sun", "Mars", "Saturn"]


def test_top_6_truncation():
    aspects = [_aspect(orb_degrees=i * 0.1) for i in range(10)]
    ranked = RANKER.rank(aspects)
    assert len(ranked) == TOP_N
    assert [r.rank for r in ranked] == [1, 2, 3, 4, 5, 6]


def test_fewer_than_6_passes_through_without_padding():
    aspects = [_aspect(orb_degrees=0.5), _aspect(orb_degrees=1.5)]
    ranked = RANKER.rank(aspects)
    assert len(ranked) == 2


def test_tie_break_prefers_tighter_orb():
    tight = _aspect(transiting_body="Mars", orb_degrees=0.1)
    wide = _aspect(transiting_body="Venus", orb_degrees=2.9)
    # Distinct scores expected (orb differs) - tighter orb should score higher
    # and thus rank first even though both are otherwise identical.
    ranked = RANKER.rank([wide, tight])
    assert ranked[0].aspect is tight


def test_tie_break_falls_back_to_input_order_on_exact_score_tie():
    first = _aspect(transiting_body="Mars", orb_degrees=1.0)
    second = _aspect(transiting_body="Mars", orb_degrees=1.0)
    ranked = RANKER.rank([first, second])
    assert ranked[0].aspect is first
    assert ranked[1].aspect is second


def test_slow_planet_to_personal_point_outranks_same_orb_moon_aspect():
    # DESIGN.md 9.5: "Moon contacts should not crowd out every slower
    # transit." At the same absolute orb, the Moon's much tighter policy
    # cap (1.5 degrees) makes its orb_closeness ratio harsher than a body
    # with no special cap, so a slow planet can still win despite Moon's
    # higher raw body weight.
    moon = _aspect(transiting_body="Moon", aspect="trine", orb_degrees=1.0, natal_target="Venus")
    saturn = _aspect(
        transiting_body="Saturn", aspect="trine", orb_degrees=1.0, natal_target="Venus"
    )
    ranked = RANKER.rank([moon, saturn])
    assert ranked[0].aspect.transiting_body == "Saturn"


def test_applying_scores_higher_than_separating_otherwise_identical():
    applying = _aspect(movement="applying")
    separating = _aspect(movement="separating")
    ranked = RANKER.rank([separating, applying])
    assert ranked[0].aspect.movement == "applying"


def test_rank_field_is_1_indexed_and_contiguous():
    aspects = [_aspect(orb_degrees=i * 0.3) for i in range(4)]
    ranked = RANKER.rank(aspects)
    assert [r.rank for r in ranked] == [1, 2, 3, 4]


def test_ranker_version_is_stable_string():
    assert RANKER.version == "transit-ranking-v1"


def test_empty_input_returns_empty_list():
    assert RANKER.rank([]) == []
