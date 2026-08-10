"""The six lines of the ground stack as one figure.

The defect this pins down: every cast line is its own `Static` with
`text-align: center`, so a changing line's trailing marker (`×`/`○`) made
its string three cells longer than a settled line's and centring pushed
the six-cell bar one or two columns to the left. Read down the stack, the
broken lines sat off the unbroken ones.

The assertion is the column the bar starts at, not the glyph strings: at
any width, and whichever of the four values a line took, the bars begin
and end together.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from textual.widgets import Static

from syzygy.domain.consultation import Consultation, ConsultationStatus
from syzygy.domain.iching import IChingCast, IChingLineValue
from syzygy.domain.oracle import OracleQuestion
from syzygy.domain.tarot import TarotDraw
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.consultation_result import ConsultationResultScreen

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)

#: All four line values at once, which no single real cast is guaranteed
#: to give us: two settled, two changing, in both polarities.
LINES = [
    IChingLineValue.OLD_YANG,
    IChingLineValue.YOUNG_YANG,
    IChingLineValue.YOUNG_YIN,
    IChingLineValue.OLD_YIN,
    IChingLineValue.YOUNG_YANG,
    IChingLineValue.OLD_YIN,
]


def consultation() -> Consultation:
    cast = IChingCast(
        lines=LINES,
        primary_hexagram_number=1,
        changing_lines=[index for index, line in enumerate(LINES, 1) if line.is_changing],
        resulting_hexagram_number=2,
        cast_at_utc=NOW,
        method_version="three-coin-v1",
        entropy_digest="00" * 32,
    )
    return Consultation(
        id="c1",
        profile_id="p1",
        question=OracleQuestion(
            text="Where do the lines fall?",
            normalized_text="Where do the lines fall?",
            asked_at_utc=NOW,
            consultation_local_date="2026-08-09",
        ),
        status=ConsultationStatus.DRAWN,
        consultation_local_timestamp=NOW.isoformat(),
        consultation_timezone="UTC",
        card_draw=TarotDraw(
            card_id="the_fool",
            drawn_at_utc=NOW,
            sortes_version="sortes-v1",
            entropy_digest="00" * 32,
        ),
        cast=cast,
        created_at_utc=NOW,
        updated_at_utc=NOW,
    )


def drawn_span(widget: Static) -> tuple[int, int]:
    """`(first, last)` cell of the rendered bar, blanks and markers aside."""
    text = "".join(segment.text for segment in widget.render_line(0))
    bar = [column for column, cell in enumerate(text) if cell == "━"]
    assert bar, f"no line drawn in {text!r}"
    return bar[0], bar[-1]


@pytest.mark.parametrize("size", [(80, 40), (81, 40), (64, 24), (65, 24)])
async def test_every_cast_line_starts_and_ends_in_the_same_column(
    services, profile, monkeypatch, size
) -> None:
    monkeypatch.setenv("SYZYGY_ANIMATIONS", "off")
    app = SyzygyApp(services)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.push_screen(ConsultationResultScreen(consultation(), interpret=False))
        await pilot.pause()

        lines = list(app.screen.query(".cast-line"))
        assert len(lines) == 6
        spans = {drawn_span(line) for line in lines}
        assert len(spans) == 1, f"bars misaligned at {size}: {sorted(spans)}"
