"""M13.2 cache and no-draw invariants through the application services."""

from __future__ import annotations

from syzygy.domain.interpretation import InterpretationContext, SummaryResult
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.storage.profiles import get_profile
from syzygy.storage.reading_service import rank_current_transits
from syzygy.storage.summary_service import cosmos_summary, natal_summary


class CountingProvider:
    provider_id = "counting"
    model_id = "counting-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.fixture = FixtureProvider()

    async def interpret(self, context: InterpretationContext):
        return await self.fixture.interpret(context)

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        self.calls += 1
        return await self.fixture.summarize(context)


async def test_natal_summary_is_cached_for_the_profile_and_never_draws(services, profile):
    provider = CountingProvider()
    first = await natal_summary(
        services.conn, profile, provider, services.clock.now_utc()
    )
    second = await natal_summary(
        services.conn, profile, provider, services.clock.now_utc()
    )
    assert first == second
    assert provider.calls == 1
    assert first.provider_id == "fixture"
    reloaded = get_profile(services.conn, profile.id)
    assert reloaded is not None
    assert reloaded.natal_summary == first
    assert services.conn.execute(
        "SELECT COUNT(*) FROM interpretive_summaries WHERE kind = 'natal_summary'"
    ).fetchone()[0] == 0
    assert services.conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0


async def test_cosmos_summary_is_cached_per_local_day_and_never_draws(services, profile):
    provider = CountingProvider()
    _, ranked = rank_current_transits(
        profile, services.astrology, services.clock.now_utc()
    )
    first = await cosmos_summary(
        services.conn, profile, ranked, provider, services.clock.now_utc()
    )
    second = await cosmos_summary(
        services.conn, profile, ranked, provider, services.clock.now_utc()
    )
    assert first == second
    assert provider.calls == 1
    assert "fixture" in first.body.lower()
    assert services.conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0
