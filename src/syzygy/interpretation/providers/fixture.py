"""A deterministic interpretation provider with no external dependencies.

Per ARCHITECTURE_HANDOFF.md section 21/37, this should be the first
provider implemented and is what the TUI, storage, and archive should be
built and tested against before any real model integration exists. It
never makes a network call, needs no API key, and costs no tokens.

The output is deliberately structured like a real reading (referencing the
actual drawn card, its astrological correspondence, and the significant
transits in the context) rather than being a placeholder string - so that
screenshots, TUI development, and reading-workflow tests see realistic
shapes and lengths.
"""

from __future__ import annotations

from syzygy.domain.interpretation import (
    ConventionalReading,
    EsotericReading,
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
    SummaryResult,
)

FIXTURE_PROMPT_VERSION = "fixture-v1"


class FixtureProvider:
    """Deterministic, offline `InterpretationProvider`.

    Same `InterpretationContext` in, same `InterpretationResult` out -
    useful for golden-file tests as well as TUI development.
    """

    provider_id = "fixture"
    model_id = "fixture-deterministic-v1"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        card = context.card
        if card is None:
            raise ValueError("daily interpretation requires a card")
        astro = card.astrology
        if astro is not None and astro.type == "planet":
            correspondence = f"the planet {astro.planet}"
        elif astro is not None and astro.type == "sign":
            correspondence = f"the sign {astro.sign}"
        elif astro is not None and astro.type == "element":
            correspondence = f"the element {card.element}"
        elif astro is not None and astro.type == "decan":
            correspondence = f"{astro.planet} in {astro.sign}"
        else:
            correspondence = "no fixed zodiacal attribution"

        transit_lines = [
            (
                f"transiting {t.aspect.transiting_body} {t.aspect.aspect} "
                f"natal {t.aspect.natal_target} ({t.aspect.orb_degrees:.2f} degrees, "
                f"{t.aspect.movement})"
            )
            for t in context.significant_transits
        ]
        transit_summary = "; ".join(transit_lines) if transit_lines else "no aspects in orb today"

        esoteric_body = (
            f"{card.full_name} enters the alignment under {correspondence}. "
            f"Today's ranked sky: {transit_summary}. "
            f"[fixture provider: replace with Book of Thoth-grounded synthesis]"
        )
        conventional_body = (
            f"The card on the table is {card.display_name}. Whatever this rank and suit "
            f"tend to mean for you, expect it to show up today, sharpened or softened by: "
            f"{transit_summary}. [fixture provider: replace with plain-language synthesis]"
        )

        return InterpretationResult(
            alignment_title=f"{context.profile_display_name} — {card.display_name}",
            esoteric=EsotericReading(
                summary=f"{card.display_name}, read under {correspondence}.",
                body=esoteric_body,
            ),
            conventional=ConventionalReading(
                summary=f"Today carries the character of {card.display_name}.",
                body=conventional_body,
                watch_for=["This is fixture output; nothing here is a real synthesis."],
                reflection="What would change if you took this card literally, just for today?",
            ),
            source_chunk_ids=[c.id for c in context.knowledge_chunks],
            provider_id=self.provider_id,
            model_id=self.model_id,
            prompt_version=FIXTURE_PROMPT_VERSION,
        )

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        """Deterministic copy so summaries never require a configured model."""
        if context.kind is InterpretationKind.NATAL_SUMMARY:
            headline = "A chart held in balance"
            body = (
                f"{context.profile_display_name}'s chart places the Sun in "
                f"{context.sun_placement.sign}, the Moon in {context.moon_placement.sign}, "
                f"with {context.ascendant_sign} rising. These are fixture notes: they show "
                "where a configured model's durable chart synthesis will appear."
            )
        elif context.kind is InterpretationKind.COSMOS_SUMMARY:
            headline = "The sky in motion"
            count = len(context.significant_transits)
            body = (
                f"Syzygy ranked {count} significant transit{'s' if count != 1 else ''} for "
                f"{context.consultation_local_date}. This fixture summary keeps the daily "
                "horoscope available without a model while leaving every astrological fact "
                "and its ranking unchanged."
            )
        else:
            raise ValueError("summarize requires a summary context")
        return SummaryResult(
            headline=headline,
            body=body,
            provider_id=self.provider_id,
            model_id=self.model_id,
            prompt_version=context.prompt_version,
        )
