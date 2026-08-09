"""Oracle orchestration with draw-before-provider ordering."""

from __future__ import annotations

import sqlite3

from syzygy.astrology.base import AstrologyEngine
from syzygy.clock import Clock
from syzygy.domain.interpretation import OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import (
    OracleConsultation,
    OracleQuestion,
    OracleStatus,
    normalize_question,
)
from syzygy.domain.profile import Profile
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.context_builder import build_oracle_context
from syzygy.interpretation.prompts import ORACLE_PROMPT_VERSION
from syzygy.knowledge.retrieve import retrieve_for_card
from syzygy.sortes.deck import get_card
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import oracle
from syzygy.storage.reading_service import (
    _select_knowledge_chunks,
    rank_current_transits,
)


def ask_question(
    conn: sqlite3.Connection, profile: Profile, clock: Clock, text: str
) -> OracleConsultation:
    """Commit the user's question before chance enters the consultation."""
    asked_at = clock.now_utc()
    local_now = asked_at.astimezone()
    question = OracleQuestion(
        text=text,
        normalized_text=normalize_question(text),
        asked_at_utc=asked_at,
        consultation_local_date=local_now.date().isoformat(),
    )
    return oracle.create_asked(
        conn,
        profile_id=profile.id,
        question=question,
        consultation_local_timestamp=local_now.isoformat(),
        consultation_timezone=local_now.tzname() or "UTC",
    )


def draw_oracle_consultation(
    conn: sqlite3.Connection,
    consultation: OracleConsultation,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
) -> OracleConsultation:
    """Commit the draw, then build context; safe to resume from status."""
    if consultation.profile_id != profile.id:
        raise ValueError("consultation does not belong to profile")
    if consultation.status is OracleStatus.ASKED:
        consultation = oracle.commit_draw(
            conn, consultation.id, draw_card(entropy, now=clock.now_utc())
        )
    if consultation.status is OracleStatus.DRAWN:
        assert consultation.card_draw is not None
        card = get_card(consultation.card_draw.card_id)
        snapshot, ranked = rank_current_transits(profile, astrology, clock.now_utc())
        hits = retrieve_for_card(conn, card.id)
        context = build_oracle_context(
            profile=profile,
            card=card,
            ranked_transits=ranked,
            knowledge_chunks=_select_knowledge_chunks(hits),
            consultation_local_timestamp=consultation.consultation_local_timestamp,
            consultation_local_date=consultation.question.consultation_local_date,
            prompt_version=ORACLE_PROMPT_VERSION,
            question=consultation.question.normalized_text,
        )
        consultation = oracle.commit_context(
            conn,
            consultation.id,
            snapshot=snapshot,
            context=context,
            citations=[RetrievedCitation.from_hit(hit) for hit in hits],
            now=clock.now_utc(),
        )
    return consultation


async def interpret_oracle(
    conn: sqlite3.Connection,
    consultation: OracleConsultation,
    clock: Clock,
    provider: InterpretationProvider,
) -> OracleConsultation:
    if consultation.status is OracleStatus.COMPLETE:
        return consultation
    if consultation.status in (OracleStatus.ASKED, OracleStatus.DRAWN):
        raise ValueError("oracle consultation has no committed context")
    if consultation.status in (
        OracleStatus.CONTEXT_READY,
        OracleStatus.INTERPRETATION_FAILED,
    ):
        consultation = oracle.begin_interpreting(
            conn, consultation.id, now=clock.now_utc()
        )
    assert consultation.interpretation_context is not None
    try:
        result = await provider.interpret(consultation.interpretation_context)
        if not isinstance(result, OracleResult):
            raise TypeError("oracle provider returned a daily result")
    except Exception:
        return oracle.fail_interpretation(
            conn,
            consultation.id,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            prompt_version=consultation.interpretation_context.prompt_version,
            now=clock.now_utc(),
        )
    return oracle.complete_interpretation(
        conn, consultation.id, result, now=clock.now_utc()
    )


async def consult_oracle(
    conn: sqlite3.Connection,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
    provider: InterpretationProvider,
    question: str,
) -> OracleConsultation:
    consultation = ask_question(conn, profile, clock, question)
    consultation = draw_oracle_consultation(
        conn, consultation, profile, clock, astrology, entropy
    )
    return await interpret_oracle(conn, consultation, clock, provider)
