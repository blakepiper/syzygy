"""Oracle orchestration: one turn of the wheel, two committed objects.

Ordering is the whole point of this module (ADR 0008 section 5). The
question is committed first, then the card and the cast together, then the
context - and only after all of that does a provider get constructed or
called. Every step is resumable from the stored status alone, so a crash
between the wheel and the interpretation resumes without redrawing the
card or recasting the lines.
"""

from __future__ import annotations

import sqlite3

from syzygy.clock import Clock
from syzygy.domain.consultation import Consultation, ConsultationStatus
from syzygy.domain.iching_consultation import IChingConsultation
from syzygy.domain.interpretation import OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import OracleConsultation, OracleQuestion, normalize_question
from syzygy.domain.profile import Profile
from syzygy.iching.cast import cast_hexagram
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.context_builder import build_consultation_context
from syzygy.interpretation.prompts import ORACLE_PROMPT_VERSION
from syzygy.knowledge.retrieve import retrieve_for_card
from syzygy.sortes.deck import get_card
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import consultations
from syzygy.storage.consultations import LegacyConsultationIsReadOnly
from syzygy.storage.reading_service import _select_knowledge_chunks


def refuse_legacy(record: object) -> None:
    """Refuse to advance a pre-M22 single-object consultation.

    The archive still reads `oracle-v1` and `iching-v1` rows; nothing may
    write to them. Their storage modules have no writers left, so this is
    belt and braces - but it is the layer a caller actually reaches, and
    it fails with an explanation rather than an `AttributeError`.
    """
    if isinstance(record, OracleConsultation):
        raise LegacyConsultationIsReadOnly("oracle-v1 Thoth")
    if isinstance(record, IChingConsultation):
        raise LegacyConsultationIsReadOnly("iching-v1")


def ask_question(
    conn: sqlite3.Connection, profile: Profile, clock: Clock, text: str
) -> Consultation:
    """Commit the user's question before chance enters the consultation."""
    asked_at = clock.now_utc()
    local_now = asked_at.astimezone()
    question = OracleQuestion(
        text=text,
        normalized_text=normalize_question(text),
        asked_at_utc=asked_at,
        consultation_local_date=local_now.date().isoformat(),
    )
    return consultations.create_asked(
        conn,
        profile_id=profile.id,
        question=question,
        consultation_local_timestamp=local_now.isoformat(),
        consultation_timezone=local_now.tzname() or "UTC",
    )


def draw_consultation(
    conn: sqlite3.Connection,
    consultation: Consultation,
    profile: Profile,
    clock: Clock,
    entropy: EntropyCollector,
) -> Consultation:
    """Commit both chance objects, then build context; resumable by status.

    One `EntropyCollector` serves both derivations: `draw_card` selects
    over the mixed digest directly and `cast_hexagram` derives one
    personalized digest per line, so the card and the six lines are
    domain-separated from each other and from every other line. Neither
    function is given a non-default `os_random`; nothing here can.
    """
    refuse_legacy(consultation)
    if consultation.profile_id != profile.id:
        raise ValueError("consultation does not belong to profile")
    if consultation.status is ConsultationStatus.ASKED:
        now = clock.now_utc()
        consultation = consultations.commit_chance(
            conn,
            consultation.id,
            draw=draw_card(entropy, now=now),
            cast=cast_hexagram(entropy, now=now),
        )
    if consultation.status is ConsultationStatus.DRAWN:
        assert consultation.card_draw is not None
        assert consultation.cast is not None
        card = get_card(consultation.card_draw.card_id)
        hits = retrieve_for_card(conn, card.id)
        context = build_consultation_context(
            profile=profile,
            card=card,
            cast=consultation.cast,
            knowledge_chunks=_select_knowledge_chunks(hits),
            consultation_local_timestamp=consultation.consultation_local_timestamp,
            consultation_local_date=consultation.question.consultation_local_date,
            prompt_version=ORACLE_PROMPT_VERSION,
            question=consultation.question.normalized_text,
        )
        consultation = consultations.commit_context(
            conn,
            consultation.id,
            context=context,
            citations=[RetrievedCitation.from_hit(hit) for hit in hits],
            now=clock.now_utc(),
        )
    return consultation


async def interpret_consultation(
    conn: sqlite3.Connection,
    consultation: Consultation,
    clock: Clock,
    provider: InterpretationProvider,
) -> Consultation:
    refuse_legacy(consultation)
    if consultation.status is ConsultationStatus.COMPLETE:
        return consultation
    if consultation.status in (ConsultationStatus.ASKED, ConsultationStatus.DRAWN):
        raise ValueError("consultation has no committed context")
    if consultation.status in (
        ConsultationStatus.CONTEXT_READY,
        ConsultationStatus.INTERPRETATION_FAILED,
    ):
        consultation = consultations.begin_interpreting(
            conn, consultation.id, now=clock.now_utc()
        )
    assert consultation.interpretation_context is not None
    try:
        result = await provider.interpret(consultation.interpretation_context)
        if not isinstance(result, OracleResult):
            raise TypeError("oracle provider returned a daily result")
    except Exception:
        return consultations.fail_interpretation(
            conn,
            consultation.id,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            prompt_version=consultation.interpretation_context.prompt_version,
            now=clock.now_utc(),
        )
    return consultations.complete_interpretation(
        conn, consultation.id, result, now=clock.now_utc()
    )


async def consult(
    conn: sqlite3.Connection,
    profile: Profile,
    clock: Clock,
    entropy: EntropyCollector,
    provider: InterpretationProvider,
    question: str,
) -> Consultation:
    consultation = ask_question(conn, profile, clock, question)
    consultation = draw_consultation(conn, consultation, profile, clock, entropy)
    return await interpret_consultation(conn, consultation, clock, provider)
