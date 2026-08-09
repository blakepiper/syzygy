"""I Ching orchestration with cast-before-provider ordering."""

from __future__ import annotations

import sqlite3

from syzygy.astrology.base import AstrologyEngine
from syzygy.clock import Clock
from syzygy.domain.iching_consultation import IChingConsultation, IChingStatus
from syzygy.domain.interpretation import OracleResult
from syzygy.domain.oracle import OracleQuestion, normalize_question
from syzygy.domain.profile import Profile
from syzygy.iching.cast import cast_hexagram
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.context_builder import build_iching_context
from syzygy.interpretation.prompts import ICHING_PROMPT_VERSION
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import iching
from syzygy.storage.reading_service import rank_current_transits


def ask_question(
    conn: sqlite3.Connection, profile: Profile, clock: Clock, text: str
) -> IChingConsultation:
    asked_at = clock.now_utc()
    local_now = asked_at.astimezone()
    question = OracleQuestion(
        text=text,
        normalized_text=normalize_question(text),
        asked_at_utc=asked_at,
        consultation_local_date=local_now.date().isoformat(),
    )
    return iching.create_asked(
        conn,
        profile_id=profile.id,
        question=question,
        consultation_local_timestamp=local_now.isoformat(),
        consultation_timezone=local_now.tzname() or "UTC",
    )


def cast_consultation(
    conn: sqlite3.Connection,
    consultation: IChingConsultation,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
) -> IChingConsultation:
    if consultation.profile_id != profile.id:
        raise ValueError("consultation does not belong to profile")
    if consultation.status is IChingStatus.ASKED:
        consultation = iching.commit_cast(
            conn, consultation.id, cast_hexagram(entropy, now=clock.now_utc())
        )
    if consultation.status is IChingStatus.CAST:
        assert consultation.cast is not None
        snapshot, ranked = rank_current_transits(profile, astrology, clock.now_utc())
        context = build_iching_context(
            profile=profile,
            cast=consultation.cast,
            ranked_transits=ranked,
            consultation_local_timestamp=consultation.consultation_local_timestamp,
            consultation_local_date=consultation.question.consultation_local_date,
            prompt_version=ICHING_PROMPT_VERSION,
            question=consultation.question.normalized_text,
        )
        consultation = iching.commit_context(
            conn,
            consultation.id,
            snapshot=snapshot,
            context=context,
            now=clock.now_utc(),
        )
    return consultation


async def interpret_iching(
    conn: sqlite3.Connection,
    consultation: IChingConsultation,
    clock: Clock,
    provider: InterpretationProvider,
) -> IChingConsultation:
    if consultation.status is IChingStatus.COMPLETE:
        return consultation
    if consultation.status in (IChingStatus.ASKED, IChingStatus.CAST):
        raise ValueError("I Ching consultation has no committed context")
    if consultation.status in (
        IChingStatus.CONTEXT_READY,
        IChingStatus.INTERPRETATION_FAILED,
    ):
        consultation = iching.begin_interpreting(
            conn, consultation.id, now=clock.now_utc()
        )
    assert consultation.interpretation_context is not None
    try:
        result = await provider.interpret(consultation.interpretation_context)
        if not isinstance(result, OracleResult):
            raise TypeError("I Ching provider returned a daily result")
    except Exception:
        return iching.fail_interpretation(
            conn,
            consultation.id,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            prompt_version=consultation.interpretation_context.prompt_version,
            now=clock.now_utc(),
        )
    return iching.complete_interpretation(
        conn, consultation.id, result, now=clock.now_utc()
    )


async def consult_iching(
    conn: sqlite3.Connection,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
    provider: InterpretationProvider,
    question: str,
) -> IChingConsultation:
    consultation = ask_question(conn, profile, clock, question)
    consultation = cast_consultation(
        conn, consultation, profile, clock, astrology, entropy
    )
    return await interpret_iching(conn, consultation, clock, provider)
