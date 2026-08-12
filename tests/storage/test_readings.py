"""Same-day idempotency, retry-without-redraw, and crash-recovery for
`syzygy.storage.reading_service.get_or_create_todays_reading`
(docs/old/IMPLEMENTATION_PLAN.md §4.3 - the literal docs/old/ARCHITECTURE_HANDOFF.md §23
test: "kill the flow after DRAWN, restart, prove the same card
survives").
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.clock import FixedClock
from syzygy.domain.astrology import (
    BirthData,
    NatalAspect,
    NatalChart,
    NatalPlacement,
    TransitSnapshot,
)
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.domain.profile import Profile
from syzygy.domain.reading import ReadingStatus
from syzygy.interpretation.prompts import PROMPT_VERSION
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.knowledge.store import replace_source
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import readings
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile
from syzygy.storage.reading_service import (
    MAX_KNOWLEDGE_CHUNKS_PER_SOURCE,
    MAX_SOURCE_PASSAGE_CHARS,
    get_or_create_todays_reading,
)

FIXED_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _fixed_os_random_factory(seed_byte: int):
    def _os_random(n: int) -> bytes:
        return bytes([seed_byte]) * n

    return _os_random


def _profile() -> Profile:
    birth_data = BirthData(
        local_date="1990-08-07",
        local_time="14:22:00",
        place_label="New York, NY",
        latitude=40.7128,
        longitude=-74.006,
        timezone="America/New_York",
    )
    natal_chart = NatalChart(
        birth_data=birth_data,
        placements=[
            NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
            NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
        ],
        aspects=[NatalAspect(body_a="Sun", body_b="Moon", aspect="square", orb_degrees=1.5)],
        ascendant_longitude=210.0,
        midheaven_longitude=120.0,
        astrology_engine="kerykeion",
        astrology_engine_version="5.12.9",
        chart_schema_version="chart-v1",
    )
    now = FIXED_NOW
    return Profile(
        id="p1",
        display_name="Blake",
        birth_data=birth_data,
        natal_chart=natal_chart,
        created_at_utc=now,
        updated_at_utc=now,
    )


class _CountingAstrologyEngine:
    """Records how many times transits are (re)computed, so tests can
    prove a reopened/resumed reading never recalculates a stage that was
    already committed.
    """

    def __init__(self) -> None:
        self.calculate_transits_calls = 0

    def calculate_natal(self, birth: BirthData) -> NatalChart:
        raise AssertionError("calculate_natal should never be called by the reading service")

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        self.calculate_transits_calls += 1
        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=[],
            raw_aspects=[],
            astrology_policy_version=POLICY_VERSION,
        )


class _FailingProvider:
    provider_id = "failing"
    model_id = "failing-v1"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise RuntimeError("simulated provider failure")


def test_first_call_creates_a_complete_reading(conn):
    profile = _profile()
    insert_profile(conn, profile)

    reading = _run(conn, profile)

    assert reading.status == ReadingStatus.COMPLETE
    assert reading.card_draw is not None
    assert reading.interpretation is not None


def test_archive_delete_removes_reading_but_permanently_occupies_its_date(conn):
    profile = _profile()
    insert_profile(conn, profile)
    reading = _run(conn, profile)

    assert readings.delete_from_archive(
        conn, reading.id, profile_id=profile.id, deleted_at=FIXED_NOW
    )
    assert readings.get_by_id(conn, reading.id) is None
    assert readings.date_was_deleted(
        conn, profile.id, reading.consultation_local_date
    )
    with pytest.raises(readings.ReadingDateArchivedError):
        readings.create_prepared(
            conn,
            profile_id=profile.id,
            consultation_local_date=reading.consultation_local_date,
            consultation_local_timestamp=FIXED_NOW.isoformat(),
            consultation_utc_timestamp=FIXED_NOW,
            consultation_timezone="UTC",
        )


def test_archive_delete_cannot_delete_another_profiles_reading(conn):
    profile = _profile()
    insert_profile(conn, profile)
    reading = _run(conn, profile)

    assert not readings.delete_from_archive(
        conn, reading.id, profile_id="someone-else", deleted_at=FIXED_NOW
    )
    assert readings.get_by_id(conn, reading.id) == reading


def test_second_call_same_day_returns_same_reading_unchanged(conn):
    profile = _profile()
    insert_profile(conn, profile)

    first = _run(conn, profile)
    engine = _CountingAstrologyEngine()
    second = _run(conn, profile, engine=engine)

    assert second == first
    assert engine.calculate_transits_calls == 0  # reopening a COMPLETE reading is a pure read


def test_crash_after_drawn_recovers_the_same_card_without_redrawing(conn):
    profile = _profile()
    insert_profile(conn, profile)

    # Simulate the pipeline crashing right after the card is committed but
    # before astrology/context/interpretation ever ran.
    reading = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=FIXED_NOW.date().isoformat(),
        consultation_local_timestamp=FIXED_NOW.isoformat(),
        consultation_utc_timestamp=FIXED_NOW,
        consultation_timezone="UTC",
    )
    collector = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    draw = draw_card(collector, now=FIXED_NOW)
    reading = readings.commit_draw(conn, reading.id, draw)
    assert reading.status == ReadingStatus.DRAWN

    # "Restart": brand new collaborator instances, same conn/profile.
    recovered = _run(conn, profile)

    assert recovered.status == ReadingStatus.COMPLETE
    assert recovered.card_draw is not None
    assert recovered.card_draw.card_id == draw.card_id
    assert recovered.card_draw.entropy_digest == draw.entropy_digest


def test_interpretation_failure_can_be_retried_without_a_new_card_id(conn):
    profile = _profile()
    insert_profile(conn, profile)

    failed = _run(conn, profile, provider=_FailingProvider())
    assert failed.status == ReadingStatus.INTERPRETATION_FAILED
    assert failed.card_draw is not None

    retried = _run(conn, profile, provider=FixtureProvider())
    assert retried.status == ReadingStatus.COMPLETE
    assert retried.card_draw is not None
    assert retried.card_draw.card_id == failed.card_draw.card_id


def test_context_uses_the_versioned_prompt_and_the_shared_context_builder(conn):
    profile = _profile()
    insert_profile(conn, profile)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    context = reading.interpretation_context
    assert context.prompt_version == PROMPT_VERSION
    # The shared builder's output, not the service's own older minimal one:
    # the luminaries arrive as relevant placements and the Ascendant as a sign.
    assert {p.body for p in context.relevant_natal_placements} >= {"Sun", "Moon"}
    assert context.ascendant_sign == "Scorpio"  # ascendant_longitude 210.0


def test_the_drawn_cards_source_passages_reach_the_context(conn):
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    _ingest_chunks(conn, card_id, "book_of_thoth", count=2)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    chunks = reading.interpretation_context.knowledge_chunks
    assert [chunk.id for chunk in chunks] == [
        f"book_of_thoth-{card_id}-0",
        f"book_of_thoth-{card_id}-1",
    ]


def test_only_the_top_few_chunks_of_each_source_reach_the_context(conn):
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    _ingest_chunks(conn, card_id, "book_of_thoth", count=MAX_KNOWLEDGE_CHUNKS_PER_SOURCE + 4)
    _ingest_chunks(conn, card_id, "duquette_companion", count=MAX_KNOWLEDGE_CHUNKS_PER_SOURCE + 4)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    chunks = reading.interpretation_context.knowledge_chunks
    per_source = Counter(chunk.source_id for chunk in chunks)
    assert per_source == {
        "book_of_thoth": MAX_KNOWLEDGE_CHUNKS_PER_SOURCE,
        "duquette_companion": MAX_KNOWLEDGE_CHUNKS_PER_SOURCE,
    }
    # Tier 0 keeps its precedence, and each source is truncated from the end.
    assert [chunk.source_id for chunk in chunks[:MAX_KNOWLEDGE_CHUNKS_PER_SOURCE]] == [
        "book_of_thoth"
    ] * MAX_KNOWLEDGE_CHUNKS_PER_SOURCE
    assert [chunk.chunk_index for chunk in chunks[:MAX_KNOWLEDGE_CHUNKS_PER_SOURCE]] == list(
        range(MAX_KNOWLEDGE_CHUNKS_PER_SOURCE)
    )


def test_long_passages_are_capped_by_a_total_character_budget(conn):
    """The count cap alone let a prompt reach ten thousand tokens against
    an 8192-token local context, which `llama-server` refuses outright -
    and since a retry reuses the committed context verbatim, that reading
    then failed identically forever."""
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    # Three sections the size the Book of Thoth actually runs to. All
    # three are within the per-source cap; two of them are not within the
    # prompt.
    _ingest_chunks(conn, card_id, "book_of_thoth", count=3, text_chars=5000)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    chunks = reading.interpretation_context.knowledge_chunks
    assert sum(len(chunk.text) for chunk in chunks) <= MAX_SOURCE_PASSAGE_CHARS
    # The most relevant one is still sent, and nothing is truncated.
    assert [chunk.id for chunk in chunks] == [f"book_of_thoth-{card_id}-0"]
    assert all(len(chunk.text) == 5000 for chunk in chunks)
    # What retrieval found is unchanged - the budget trims what the model
    # sees, never what the `[I]` view tells the user (M18.1f).
    assert len(reading.retrieved_citations) == 3


def test_one_long_tier0_passage_does_not_crowd_out_a_short_companion(conn):
    """Same reasoning as the per-source cap: the budget skips a passage
    that does not fit and keeps considering the rest."""
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    # Two Tier 0 sections that cannot both fit, and one short companion
    # passage that fits beside either of them.
    _ingest_chunks(
        conn, card_id, "book_of_thoth", count=2, text_chars=MAX_SOURCE_PASSAGE_CHARS - 500
    )
    _ingest_chunks(conn, card_id, "duquette_companion", count=1, text_chars=200)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    chunks = reading.interpretation_context.knowledge_chunks
    assert [chunk.id for chunk in chunks] == [
        f"book_of_thoth-{card_id}-0",
        f"duquette_companion-{card_id}-0",
    ]


def test_a_passage_larger_than_the_whole_budget_is_left_out(conn):
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    _ingest_chunks(
        conn, card_id, "book_of_thoth", count=1, text_chars=MAX_SOURCE_PASSAGE_CHARS + 1
    )

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    assert reading.interpretation_context.knowledge_chunks == []
    # The prompt then says plainly that no passages were supplied, and the
    # citation still records where the card is discussed.
    assert len(reading.retrieved_citations) == 1


def test_citation_only_chunks_are_recorded_on_the_reading_but_never_sent(conn):
    """M18.1a. The bare-install case: every chunk is a citation, so the
    provider gets nothing and the reading still knows where to look."""
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    _ingest_chunks(conn, card_id, "book_of_thoth", count=2, with_text=False)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    assert reading.interpretation_context.knowledge_chunks == []
    assert [citation.chunk_id for citation in reading.retrieved_citations] == [
        f"book_of_thoth-{card_id}-0",
        f"book_of_thoth-{card_id}-1",
    ]
    assert all(not citation.text_available for citation in reading.retrieved_citations)
    assert all(citation.tier == 0 for citation in reading.retrieved_citations)


def test_retrieved_citations_cover_every_hit_not_only_the_ones_sent(conn):
    """M18.1a/M18.1f. The per-source cap trims what the model sees; it must
    not trim what the user is told retrieval found."""
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    total = MAX_KNOWLEDGE_CHUNKS_PER_SOURCE + 4
    _ingest_chunks(conn, card_id, "book_of_thoth", count=total)
    _ingest_chunks(conn, card_id, "duquette_companion", count=total)

    reading = _run(conn, profile)

    assert reading.interpretation_context is not None
    assert len(reading.interpretation_context.knowledge_chunks) == (
        2 * MAX_KNOWLEDGE_CHUNKS_PER_SOURCE
    )
    assert len(reading.retrieved_citations) == 2 * total
    tiers = Counter(citation.tier for citation in reading.retrieved_citations)
    assert tiers == {0: total, 1: total}
    # Tier 0 first, the same ordering retrieval returned.
    assert [citation.tier for citation in reading.retrieved_citations[:total]] == [0] * total
    assert all(
        citation.retrieval_method == "structural" for citation in reading.retrieved_citations
    )
    # Every chunk the provider was given also appears as a citation.
    sent = {chunk.id for chunk in reading.interpretation_context.knowledge_chunks}
    assert sent <= {citation.chunk_id for citation in reading.retrieved_citations}


def test_retrieved_citations_survive_a_reopen(conn):
    profile = _profile()
    insert_profile(conn, profile)
    card_id = _todays_card_id()
    _ingest_chunks(conn, card_id, "book_of_thoth", count=2, with_text=False)

    reading = _run(conn, profile)
    reopened = readings.get_by_id(conn, reading.id)

    assert reopened is not None
    assert reopened.retrieved_citations == reading.retrieved_citations


def test_an_empty_knowledge_base_still_produces_a_reading(conn):
    profile = _profile()
    insert_profile(conn, profile)

    reading = _run(conn, profile)

    assert reading.status == ReadingStatus.COMPLETE
    assert reading.interpretation_context is not None
    assert reading.interpretation_context.knowledge_chunks == []
    assert reading.retrieved_citations == []


def test_card_and_suit_frequency_count_committed_draws(conn):
    profile = _profile()
    insert_profile(conn, profile)

    _commit_reading_with_card(conn, profile, "2026-08-01", "the_fool")
    _commit_reading_with_card(conn, profile, "2026-08-02", "two_of_wands")
    _commit_reading_with_card(conn, profile, "2026-08-03", "two_of_wands")
    _commit_reading_with_card(conn, profile, "2026-08-04", "ace_of_wands")

    assert readings.card_frequency(conn, profile.id) == {
        "two_of_wands": 2,
        "ace_of_wands": 1,
        "the_fool": 1,
    }
    assert readings.suit_frequency(conn, profile.id) == {"wands": 3, "major": 1}


def test_frequency_ignores_readings_that_never_reached_a_committed_card(conn):
    profile = _profile()
    insert_profile(conn, profile)

    # PREPARED, with no card_id yet.
    readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date="2026-08-05",
        consultation_local_timestamp=FIXED_NOW.isoformat(),
        consultation_utc_timestamp=FIXED_NOW,
        consultation_timezone="UTC",
    )

    assert readings.card_frequency(conn, profile.id) == {}
    assert readings.suit_frequency(conn, profile.id) == {}


def _commit_reading_with_card(conn, profile, local_date: str, card_id: str) -> None:
    from syzygy.domain.tarot import TarotDraw

    reading = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=local_date,
        consultation_local_timestamp=FIXED_NOW.isoformat(),
        consultation_utc_timestamp=FIXED_NOW,
        consultation_timezone="UTC",
    )
    draw = TarotDraw(
        card_id=card_id,
        drawn_at_utc=FIXED_NOW,
        sortes_version="sortes-v1",
        entropy_digest="digest",
    )
    readings.commit_draw(conn, reading.id, draw)


def _todays_card_id() -> str:
    """The card `_run` will draw - same collector inputs, same card."""
    collector = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    return draw_card(collector, now=FIXED_NOW).card_id


def _ingest_chunks(
    conn,
    card_id: str,
    source_type: str,
    *,
    count: int,
    with_text: bool = True,
    text_chars: int | None = None,
) -> None:
    """Install `count` chunks for one card.

    `with_text=False` is the citation-only shape every install ships
    (M13.3): real rows, real page ranges, empty passages. `text_chars`
    pads each passage to that length, for the sizes a real book section
    actually reaches.
    """

    def _text(index: int) -> str:
        if not with_text:
            return ""
        passage = f"{source_type} passage {index} for {card_id}."
        if text_chars is None:
            return passage
        return passage.ljust(text_chars, " ")[:text_chars]

    replace_source(
        conn,
        KnowledgeSource(
            id=source_type,
            source_type=source_type,
            title=source_type,
            file_hash=f"hash-{source_type}",
            ingestion_version="test-v1",
            created_at_utc=FIXED_NOW,
        ),
        [
            KnowledgeChunk(
                id=f"{source_type}-{card_id}-{index}",
                source_id=source_type,
                section_id=card_id,
                section_type="card",
                card_id=card_id,
                title=card_id,
                page_start=100 + index,
                page_end=100 + index,
                chunk_index=index,
                text=_text(index),
                text_hash=f"text-hash-{source_type}-{index}",
            )
            for index in range(count)
        ],
    )


def _run(conn, profile, *, engine=None, provider=None):
    engine = engine or _CountingAstrologyEngine()
    provider = provider or FixtureProvider()
    collector = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    clock = FixedClock(FIXED_NOW)
    return _await(
        get_or_create_todays_reading(conn, profile, clock, engine, collector, provider)
    )


def _await(coro):
    import asyncio

    return asyncio.run(coro)
