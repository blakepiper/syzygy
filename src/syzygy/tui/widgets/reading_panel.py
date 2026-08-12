"""The reading itself, in its three views.

Esoteric and Conventional are two registers of one synthesis, not two
readings (docs/old/DESIGN.md section 4.2), so they are views over the same stored
`InterpretationResult` rather than separately fetched content. The third
view - INPUTS - shows the exact facts the model was given, which is a
product requirement, not a debug affordance (docs/old/DESIGN.md section 14.3).

Every view renders stored data verbatim. Reopening a reading never
recalculates astrology and never re-runs a provider.
"""

from __future__ import annotations

from enum import StrEnum

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from syzygy.domain.interpretation import InterpretationContext
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.tui import palette
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs, format_degrees
from syzygy.tui.widgets.tarot_card import correspondence_label
from syzygy.tui.widgets.transit_badge import format_transit

_HEADING = f"bold {palette.ACCENT}"
_BODY = palette.BONE
_MUTED = palette.MUTED
_WARNING = f"bold {palette.EMBER}"


class ReadingView(StrEnum):
    ESOTERIC = "esoteric"
    CONVENTIONAL = "conventional"
    INPUTS = "inputs"


def _esoteric_text(reading: Reading) -> Text:
    result = reading.interpretation
    assert result is not None
    text = Text()
    text.append("ESOTERIC\n\n", style=_HEADING)
    text.append(f"{result.esoteric.summary}\n\n", style=_BODY)
    text.append(f"{result.esoteric.body}\n", style=_BODY)
    return text


def _conventional_text(reading: Reading) -> Text:
    result = reading.interpretation
    assert result is not None
    conventional = result.conventional
    text = Text()
    text.append("TODAY\n\n", style=_HEADING)
    text.append(f"{conventional.summary}\n\n", style=_BODY)
    text.append(f"{conventional.body}\n", style=_BODY)
    if conventional.watch_for:
        text.append("\nWATCH FOR\n", style=_HEADING)
        for item in conventional.watch_for:
            text.append(f"• {item}\n", style=_BODY)
    text.append("\nREFLECT\n", style=_HEADING)
    text.append(f"{conventional.reflection}\n", style=_BODY)
    return text


#: The one sentence a citation-only install gets, and the action that
#: changes it (M18.1b). Syzygy ships the references to all three books
#: because they are its own derived index; it ships none of the prose,
#: because that is the books
#: (docs/adr/0003-ship-derived-knowledge-index-without-source-text.md).
NO_PASSAGES_NOTE = (
    "Syzygy ships the references to these pages but not the book text, "
    "which is still under copyright — so no passages were sent."
)
NO_PASSAGES_ACTION = "Press [K] on the home screen to ingest your own copies of the books."


def _append_source_material(
    text: Text, reading: Reading, context: InterpretationContext
) -> None:
    """The two lists the `[I]` view owes the user (M18.1b).

    They answer different questions and used to be conflated into one
    heading that said "no source chunks were supplied to the model" and
    stopped there - true, unexplained, and an apparent dead end. What was
    *sent* comes from the interpretation context; where the card is
    *discussed* comes from the reading's own retrieved citations, which
    are populated on every install because the bundled artifact carries
    them for all 78 cards.
    """
    text.append("\nPASSAGES SENT TO THE MODEL\n", style=_HEADING)
    if context.knowledge_chunks:
        for chunk in context.knowledge_chunks:
            text.append(
                f"  {chunk.title} (pages {chunk.page_start}-{chunk.page_end}) [{chunk.id}]\n",
                style=_BODY,
            )
    else:
        # docs/old/DESIGN.md section 23: never imply Crowley grounding that was not
        # actually retrieved.
        text.append("  none.\n", style=_MUTED)
        text.append(f"  {NO_PASSAGES_NOTE}\n", style=_MUTED)
        text.append(f"  {NO_PASSAGES_ACTION}\n", style=_MUTED)

    text.append("\nWHERE THIS CARD IS DISCUSSED\n", style=_HEADING)
    if reading.retrieved_citations:
        for citation in reading.retrieved_citations:
            tier = "canonical" if citation.tier == 0 else "supplementary"
            sent = "sent" if citation.text_available else "citation only"
            text.append(f"  {citation.reference}\n", style=_BODY)
            text.append(f"    {tier} · {citation.retrieval_method} · {sent}\n", style=_MUTED)
    else:
        # Only reachable on a build with no bundled artifact, or a reading
        # committed before migration 6 - both real, neither the norm.
        text.append("  no citations were recorded for this reading.\n", style=_MUTED)


def _inputs_text(reading: Reading, glyphs: GlyphSet) -> Text:
    text = Text()
    text.append("INPUTS\n\n", style=_HEADING)

    context = reading.interpretation_context
    if context is None:
        text.append("No interpretation context has been built yet.\n", style=_MUTED)
        return text

    card = context.card
    assert card is not None  # stored reading contexts are validated to require it
    text.append("CARD\n", style=_HEADING)
    text.append(f"  {card.full_name} ({card.id})\n", style=_BODY)
    text.append(f"  {correspondence_label(card, glyphs)}\n", style=_BODY)
    if card.hebrew_letter:
        text.append(f"  Hebrew letter {card.hebrew_letter}\n", style=_MUTED)
    if card.qabalah.sephira or card.qabalah.path_number:
        qabalah = card.qabalah.sephira or f"path {card.qabalah.path_number}"
        text.append(f"  Qabalah: {qabalah}\n", style=_MUTED)
    if reading.card_draw is not None:
        text.append(f"  Drawn {reading.card_draw.drawn_at_utc.isoformat()}\n", style=_MUTED)
        text.append(
            f"  {reading.card_draw.sortes_version} / entropy "
            f"{reading.card_draw.entropy_digest[:16]}…\n",
            style=_MUTED,
        )

    text.append("\nSELECTED TRANSITS\n", style=_HEADING)
    if context.significant_transits:
        for ranked in context.significant_transits:
            text.append(
                f"  #{ranked.rank} {format_transit(ranked, glyphs)}  score {ranked.score:.3f}\n",
                style=_BODY,
            )
    else:
        text.append("  none in orb\n", style=_MUTED)

    text.append("\nNATAL PLACEMENTS SUPPLIED\n", style=_HEADING)
    for placement in context.relevant_natal_placements:
        retrograde = " ℞" if placement.retrograde else ""
        text.append(
            f"  {glyphs.body(placement.body)} {placement.body:<10} "
            f"{glyphs.sign(placement.sign)} {placement.sign:<12} "
            f"{format_degrees(placement.longitude)}{retrograde}\n",
            style=_BODY,
        )
    text.append(f"  Ascendant sign: {context.ascendant_sign}\n", style=_BODY)

    _append_source_material(text, reading, context)

    text.append("\nPROVENANCE\n", style=_HEADING)
    text.append(f"  provider: {reading.provider_id or '—'}\n", style=_BODY)
    text.append(f"  model: {reading.model_id or '—'}\n", style=_BODY)
    text.append(f"  prompt version: {context.prompt_version}\n", style=_BODY)
    text.append(f"  context schema: {context.context_schema_version}\n", style=_BODY)
    if reading.transit_snapshot is not None:
        text.append(
            f"  astrology policy: {reading.transit_snapshot.astrology_policy_version}\n",
            style=_BODY,
        )
    text.append(f"  consultation: {reading.consultation_local_timestamp}\n", style=_BODY)
    return text


def _pending_text(
    reading: Reading, *, interrupted: bool = False, in_flight: bool = False
) -> Text:
    text = Text()
    if in_flight:
        # A retry is running right now. Checked before the stored status,
        # which still reads INTERPRETATION_FAILED until the call returns.
        # The panel stays empty: the title above already carries
        # "THE ALIGNMENT IS FIXED." and the waiting indicator
        # (`syzygy.tui.widgets.waiting`) carries the activity, down to a
        # still frame with its label at motion `off`.
        return text
    if reading.status == ReadingStatus.INTERPRETATION_FAILED:
        # The copy docs/old/DESIGN.md section 23 specifies is "the alignment is
        # fixed; interpretation is unavailable" - the oracle stands even
        # when the interpreter does not. The first half of it is the
        # title's (`ReadingScreen._show`), so this says the second half
        # once rather than printing the headline underneath itself.
        text.append("INTERPRETATION IS UNAVAILABLE.\n", style=_WARNING)
        text.append(
            "The card and the transits are committed and will not change.\n\n", style=_MUTED
        )
        text.append("[R] Retry interpretation\n", style=_BODY)
        text.append("[I] Inspect inputs\n", style=_BODY)
        return text
    if interrupted:
        # A stored INTERPRETING that nothing is working on - the previous
        # attempt was cut short rather than failing (M11.4). Same card,
        # same context, still retryable.
        text.append("INTERPRETATION WAS INTERRUPTED.\n", style=_WARNING)
        text.append(
            "The card and the transits are committed and will not change.\n\n", style=_MUTED
        )
        text.append("[R] Retry interpretation\n", style=_BODY)
        text.append("[I] Inspect inputs\n", style=_BODY)
        return text
    text.append("INTERPRETATION IN PROGRESS…\n", style=_MUTED)
    return text


class ReadingPanel(VerticalScroll):
    """Scrollable body of the reading screen, switched between views."""

    def __init__(self, *, glyphs: GlyphSet | None = None, id: str | None = None) -> None:
        super().__init__(id=id)
        self._glyphs = glyphs or default_glyphs()
        self._body = Static(id="reading-body")
        self.view = ReadingView.ESOTERIC

    def compose(self) -> ComposeResult:
        yield self._body

    def show(
        self,
        reading: Reading,
        view: ReadingView,
        *,
        interrupted: bool = False,
        in_flight: bool = False,
    ) -> None:
        """Render `view` of `reading`, falling back to the pending/failed
        state when there is no interpretation to show yet.

        `interrupted` and `in_flight` are the caller's answer to "is
        anything actually working on this right now?" - the panel cannot
        tell from the reading alone. A stored `INTERPRETING` looks
        identical whether a call is in flight or the process that started
        it died, and a retry in flight still reads as
        `INTERPRETATION_FAILED` until the call returns.
        """
        self.view = view
        if view == ReadingView.INPUTS:
            self._body.update(_inputs_text(reading, self._glyphs))
            return
        if reading.interpretation is None:
            self._body.update(
                _pending_text(reading, interrupted=interrupted, in_flight=in_flight)
            )
            return
        if view == ReadingView.ESOTERIC:
            self._body.update(_esoteric_text(reading))
        else:
            self._body.update(_conventional_text(reading))
        self.scroll_home(animate=False)
