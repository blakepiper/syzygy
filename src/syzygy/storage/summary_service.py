"""Build, generate, and cache chart/cosmos summaries without drawing."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from syzygy.domain.astrology import RankedTransit
from syzygy.domain.interpretation import InterpretationKind, SummaryResult
from syzygy.domain.profile import Profile
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.context_builder import (
    build_cosmos_summary_context,
    build_natal_summary_context,
)
from syzygy.interpretation.prompts import (
    COSMOS_SUMMARY_PROMPT_VERSION,
    NATAL_SUMMARY_PROMPT_VERSION,
)
from syzygy.storage.summaries import NATAL_SCOPE_DATE, get_summary, save_summary


def _local_now(profile: Profile, now_utc: datetime) -> datetime:
    return now_utc.astimezone(ZoneInfo(profile.birth_data.timezone))


async def natal_summary(
    conn: sqlite3.Connection,
    profile: Profile,
    provider: InterpretationProvider,
    now_utc: datetime,
) -> SummaryResult:
    cached = get_summary(
        conn, profile.id, InterpretationKind.NATAL_SUMMARY, NATAL_SCOPE_DATE
    )
    if cached is not None:
        return cached
    local = _local_now(profile, now_utc)
    context = build_natal_summary_context(
        profile,
        local.isoformat(),
        local.date().isoformat(),
        NATAL_SUMMARY_PROMPT_VERSION,
    )
    result = await provider.summarize(context)
    save_summary(conn, profile.id, context, result, now_utc)
    return result


async def cosmos_summary(
    conn: sqlite3.Connection,
    profile: Profile,
    ranked_transits: list[RankedTransit],
    provider: InterpretationProvider,
    now_utc: datetime,
) -> SummaryResult:
    local = _local_now(profile, now_utc)
    local_date = local.date().isoformat()
    cached = get_summary(
        conn, profile.id, InterpretationKind.COSMOS_SUMMARY, local_date
    )
    if cached is not None:
        return cached
    context = build_cosmos_summary_context(
        profile,
        ranked_transits,
        local.isoformat(),
        local_date,
        COSMOS_SUMMARY_PROMPT_VERSION,
    )
    result = await provider.summarize(context)
    save_summary(conn, profile.id, context, result, now_utc)
    return result
