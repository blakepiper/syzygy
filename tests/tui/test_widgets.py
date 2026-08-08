"""Deterministic widget formatting: glyph fallbacks, correspondences,
orbs, and the alignment axis.

These are the parts of the interface that carry canonical data, so they
are tested directly against the real deck rather than through a screen.
"""

from __future__ import annotations

import pytest

from syzygy.domain.astrology import RankedTransit, TransitAspect
from syzygy.sortes.deck import get_card, load_deck
from syzygy.tui.widgets.alignment import AlignmentWidget
from syzygy.tui.widgets.card_art import art_relative_path, render_card_pixels
from syzygy.tui.widgets.glyph import (
    ASCII_GLYPHS,
    UNICODE_GLYPHS,
    format_degrees,
    format_orb,
)
from syzygy.tui.widgets.tarot_card import correspondence_label
from syzygy.tui.widgets.transit_badge import format_transit


def test_every_card_has_a_renderable_correspondence():
    for card in load_deck():
        label = correspondence_label(card, UNICODE_GLYPHS)
        assert label and "\n" not in label


def test_every_card_has_bundled_art_that_renders():
    """The artwork is reference data: every deck card must resolve to it."""
    for card in load_deck():
        relative_path = art_relative_path(card.id)
        assert relative_path is not None
        assert relative_path.endswith(".png")
        assert render_card_pixels(card.id, (22, 17)) is not None


@pytest.mark.parametrize(
    ("card_id", "expected"),
    [
        ("the_hermit", "VIRGO"),  # sign-attributed trump
        ("the_magus", "MERCURY"),  # planet-attributed trump
        ("two_of_wands", "MARS"),  # decan: planet in sign
        ("knight_of_wands", "SCORPIO"),  # counter-elemental court span
    ],
)
def test_correspondences_come_from_the_deck(card_id, expected):
    assert expected in correspondence_label(get_card(card_id), UNICODE_GLYPHS)


def test_princess_cards_state_that_they_have_no_zodiacal_attribution():
    # The source text is explicit about this; the interface must not
    # invent one to fill the space.
    label = correspondence_label(get_card("princess_of_wands"), UNICODE_GLYPHS)
    assert "NO ZODIACAL ATTRIBUTION" in label or "FIRE" in label
    assert get_card("princess_of_wands").astrology is None


def test_ascii_fallbacks_avoid_unicode_glyphs():
    assert UNICODE_GLYPHS.body("Saturn") == "♄"
    assert ASCII_GLYPHS.body("Saturn") == "SA"
    assert ASCII_GLYPHS.sign("Sagittarius").isascii()
    assert ASCII_GLYPHS.aspect("square").isascii()
    assert all(glyph.isascii() for glyph in ASCII_GLYPHS.rim)
    assert correspondence_label(get_card("the_hermit"), ASCII_GLYPHS).isascii()


@pytest.mark.parametrize(
    ("longitude", "expected"),
    [(164.37, "14°22'"), (0.0, "0°00'"), (29.999, "30°00'")],
)
def test_degree_formatting(longitude, expected):
    assert format_degrees(longitude) == expected


def test_orb_formatting():
    assert format_orb(0.8) == "0°48'"
    assert format_orb(1.0) == "1°00'"


def test_transit_badge_shows_bodies_aspect_orb_and_movement():
    ranked = RankedTransit(
        aspect=TransitAspect(
            transiting_body="Saturn",
            natal_target="Venus",
            aspect="square",
            orb_degrees=0.8,
            movement="applying",
        ),
        score=0.9,
        rank=1,
    )
    assert format_transit(ranked, UNICODE_GLYPHS) == "♄ □ ♀ 0°48' applying"
    # Movement is spelled out, so it never depends on color alone.
    assert "applying" in format_transit(ranked, ASCII_GLYPHS)


async def test_alignment_lights_points_as_they_resolve():
    from textual.app import App, ComposeResult

    class Harness(App[None]):
        def compose(self) -> ComposeResult:
            yield AlignmentWidget(id="alignment")

    async with Harness().run_test(size=(80, 24)) as pilot:
        alignment = pilot.app.query_one("#alignment", AlignmentWidget)
        rendered = alignment.render().plain
        assert "SELF" in rendered and "COSMOS" in rendered and "CHANCE" in rendered
        assert rendered.count("○") == 3

        alignment.self_resolved = True
        alignment.cosmos_resolved = True
        await pilot.pause()
        rendered = alignment.render().plain
        assert rendered.count("●") == 2
        assert rendered.count("○") == 1
        assert "─" in rendered  # the resolved span is drawn solid
