from syzygy.domain.tarot import Arcana, CourtRank, Suit
from syzygy.sortes.deck import get_card, load_deck


def test_deck_has_78_cards():
    assert len(load_deck()) == 78


def test_deck_has_22_major_and_56_minor():
    deck = load_deck()
    majors = [c for c in deck if c.arcana == Arcana.MAJOR]
    minors = [c for c in deck if c.arcana == Arcana.MINOR]
    assert len(majors) == 22
    assert len(minors) == 56


def test_deck_card_ids_are_unique():
    deck = load_deck()
    ids = [c.id for c in deck]
    assert len(ids) == len(set(ids))


def test_deck_suit_sizes_are_14():
    deck = load_deck()
    for suit in Suit:
        suit_cards = [c for c in deck if c.suit == suit]
        assert len(suit_cards) == 14, f"{suit} had {len(suit_cards)} cards"


def test_deck_court_structure_is_4x4():
    deck = load_deck()
    for court in CourtRank:
        court_cards = [c for c in deck if c.court == court]
        assert len(court_cards) == 4, f"{court} had {len(court_cards)} cards"
    total_court = [c for c in deck if c.court is not None]
    assert len(total_court) == 16


def test_no_card_has_an_orientation_field():
    # v0.1 draws upright cards only (DESIGN.md 8.1). If a future change
    # adds reversals, it must not be by bolting a field onto TarotCard.
    from syzygy.domain.tarot import TarotCard

    assert "orientation" not in TarotCard.model_fields
    assert "reversed" not in TarotCard.model_fields


def test_get_card_returns_expected_card():
    card = get_card("the_fool")
    assert card.display_name == "The Fool"
    assert card.arcana == Arcana.MAJOR


def test_get_card_unknown_id_raises_key_error():
    import pytest

    with pytest.raises(KeyError):
        get_card("not_a_real_card")


def test_princesses_have_no_zodiacal_attribution():
    deck = load_deck()
    princesses = [c for c in deck if c.court == CourtRank.PRINCESS]
    assert len(princesses) == 4
    for princess in princesses:
        assert princess.astrology is None


def test_knight_of_wands_has_the_documented_counter_elemental_span():
    # Regression guard for docs/THOTH_INGESTION_MAP.md section 11: this is
    # the specific, source-verified, counter-intuitive attribution - not
    # simply "Aries" (the suit's own cardinal fire sign).
    card = get_card("knight_of_wands")
    assert card.astrology is not None
    assert card.astrology.court_span is not None
    assert card.astrology.court_span.start_sign == "Scorpio"
    assert card.astrology.court_span.end_sign == "Sagittarius"


def test_the_emperor_and_the_star_carry_the_crowley_letter_swap():
    # Regression guard for docs/THOTH_INGESTION_MAP.md section 11 (Liber AL
    # vel Legis II:76: "Tzaddi is not the Star").
    emperor = get_card("the_emperor")
    star = get_card("the_star")
    assert emperor.hebrew_letter == "Tzaddi"
    assert emperor.astrology.sign == "Aries"
    assert star.hebrew_letter == "Heh"
    assert star.astrology.sign == "Aquarius"
