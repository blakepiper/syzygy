"""The smoke test, and atomic activation (M16.8e).

The two properties that matter most are negative ones: verification must
not activate a provider on partial success, and it must not touch the
readings database at all. Both are asserted directly - the second by
hashing the database file before and after.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from syzygy.domain.interpretation import (
    ConventionalReading,
    EsotericReading,
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
    SummaryResult,
)
from syzygy.interpretation.prompts import PROMPT_VERSION
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.interpretation.providers.selection import (
    ProviderSelection,
    load_selection,
    save_selection,
)
from syzygy.local_models.contracts import FailureKind
from syzygy.local_models.settings import (
    LocalModelSettings,
    ManagementMode,
    ModelRecord,
    RuntimeRecord,
    VerificationRecord,
    load_local_model_settings,
    save_local_model_settings,
)
from syzygy.local_models.verification import (
    activate_after_smoke_test,
    needs_reverification,
    run_smoke_test,
    smoke_test_contexts,
    validate_managed_configuration,
)


class BrokenProvider:
    """Answers readings but not summaries - a partial success, which must
    count as a failure."""

    provider_id = "broken"
    model_id = "broken"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        return InterpretationResult(
            alignment_title="t",
            esoteric=EsotericReading(summary="s", body="b"),
            conventional=ConventionalReading(summary="s", body="b", reflection="r"),
            provider_id=self.provider_id,
            model_id=self.model_id,
            prompt_version=context.prompt_version,
        )

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        raise ValueError("this server ignored the summary schema")


class DeadProvider:
    provider_id = "dead"
    model_id = "dead"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise ConnectionError("connection refused")

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        raise ConnectionError("connection refused")


# -- the contexts ------------------------------------------------------------


def test_the_smoke_test_covers_all_three_shapes() -> None:
    kinds = [context.kind for context in smoke_test_contexts()]

    assert kinds == [
        InterpretationKind.DAILY_READING,
        InterpretationKind.NATAL_SUMMARY,
        InterpretationKind.COSMOS_SUMMARY,
    ]


def test_the_smoke_contexts_are_synthetic_and_carry_no_real_profile() -> None:
    for context in smoke_test_contexts():
        assert context.profile_display_name == "Verification"
        assert context.knowledge_chunks == []


def test_the_smoke_contexts_are_identical_between_runs() -> None:
    first = [context.model_dump_json() for context in smoke_test_contexts()]
    second = [context.model_dump_json() for context in smoke_test_contexts()]

    assert first == second


# -- running it --------------------------------------------------------------


def test_a_working_provider_passes_every_capability() -> None:
    result = run_smoke_test(FixtureProvider())

    assert result.passed is True
    assert [item.name for item in result.capabilities] == [
        "daily reading",
        "natal summary",
        "cosmos summary",
    ]
    assert result.failure is None


def test_a_partial_success_is_a_failure_with_per_capability_detail() -> None:
    result = run_smoke_test(BrokenProvider())

    assert result.passed is False
    assert result.capabilities[0].passed is True
    assert result.capabilities[1].passed is False
    failure = result.failure
    assert failure is not None
    assert failure.kind is FailureKind.SMOKE_TEST_FAILED
    assert "natal summary" in (failure.detail or "")


def test_a_dead_server_fails_without_raising() -> None:
    result = run_smoke_test(DeadProvider())

    assert result.passed is False
    assert all(item.passed is False for item in result.capabilities)


# -- activation --------------------------------------------------------------


def activate(settings_path: Path, provider):
    return activate_after_smoke_test(
        settings_path,
        provider=provider,
        base_url="http://127.0.0.1:18080/v1",
        served_model_id="qwen3-8b",
        runtime_version="b10331",
        artifact_id="qwen3-8b-instruct-q4-k-m",
        catalog_version="2026-08-08",
    )


def test_a_passing_smoke_test_activates_and_records_the_versions(settings_path) -> None:
    outcome = activate(settings_path, FixtureProvider())

    assert outcome.activated is True
    selection = load_selection(settings_path)
    assert selection is not None
    assert selection.provider_id == "llama_cpp"
    assert selection.base_url == "http://127.0.0.1:18080/v1"

    record = load_local_model_settings(settings_path).last_verification
    assert record is not None
    assert record.runtime_version == "b10331"
    assert record.prompt_version == PROMPT_VERSION


def test_a_failing_smoke_test_activates_nothing(settings_path) -> None:
    outcome = activate(settings_path, BrokenProvider())

    assert outcome.activated is False
    assert load_selection(settings_path) is None
    assert load_local_model_settings(settings_path).last_verification is None


def test_a_failure_restores_the_previous_provider_exactly(settings_path) -> None:
    save_selection(
        settings_path, ProviderSelection(provider_id="anthropic", model_id="claude-x")
    )

    activate(settings_path, DeadProvider())

    restored = load_selection(settings_path)
    assert restored is not None
    assert restored.provider_id == "anthropic"
    assert restored.model_id == "claude-x"


def test_activation_does_not_disturb_other_settings_sections(settings_path) -> None:
    from syzygy.settings import save_section

    save_section(settings_path, "audio", {"muted": True})

    activate(settings_path, FixtureProvider())

    from syzygy.settings import load_section

    assert load_section(settings_path, "audio") == {"muted": True}


def test_verification_never_touches_the_readings_database(tmp_path) -> None:
    """M16.8b's hard requirement, asserted the only way that means
    anything: the file's bytes are identical afterwards."""
    from syzygy.storage.database import connect
    from syzygy.storage.migrations import apply_all

    database = tmp_path / "syzygy.db"
    connection = connect(database)
    apply_all(connection)
    connection.close()

    before = hashlib.sha256(database.read_bytes()).hexdigest()
    activate(tmp_path / "settings.json", FixtureProvider())
    after = hashlib.sha256(database.read_bytes()).hexdigest()

    assert before == after


# -- re-verification ---------------------------------------------------------


def verified_settings(**overrides) -> LocalModelSettings:
    defaults = dict(
        verified_at_utc="2026-01-01T00:00:00+00:00",
        runtime_version="b10331",
        artifact_id="a",
        catalog_version="2026-08-08",
        prompt_version=PROMPT_VERSION,
        served_model_id="m",
    )
    defaults.update(overrides)
    return LocalModelSettings(last_verification=VerificationRecord(**defaults))


def test_an_unverified_setup_needs_verification() -> None:
    stale, why = needs_reverification(
        LocalModelSettings(), runtime_version="b1", catalog_version="c"
    )
    assert stale is True
    assert "never been verified" in why


def test_a_matching_record_does_not_need_reverification() -> None:
    stale, _ = needs_reverification(
        verified_settings(), runtime_version="b10331", catalog_version="2026-08-08"
    )
    assert stale is False


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"runtime_version": "b99999"}, "model runner changed"),
        ({"catalog_version": "2099-01-01"}, "catalogue changed"),
    ],
)
def test_any_version_moving_invalidates_the_evidence(kwargs, fragment: str) -> None:
    call = {"runtime_version": "b10331", "catalog_version": "2026-08-08"}
    call.update(kwargs)
    stale, why = needs_reverification(verified_settings(), **call)

    assert stale is True
    assert fragment in why


def test_a_changed_prompt_version_invalidates_the_evidence() -> None:
    stale, why = needs_reverification(
        verified_settings(prompt_version="daily-v0"),
        runtime_version="b10331",
        catalog_version="2026-08-08",
    )
    assert stale is True
    assert "prompts changed" in why


# -- startup validation ------------------------------------------------------


def configured(tmp_path, settings_path, **overrides) -> Path:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"\0" * 64)
    runtime = tmp_path / "llama-server"
    runtime.write_text("x")
    settings = LocalModelSettings(
        mode=ManagementMode.MANAGED,
        model=ModelRecord(path=str(model), size_bytes=64, syzygy_owned=True),
        runtime=RuntimeRecord(path=str(runtime), version="b10331"),
        last_verification=VerificationRecord(
            verified_at_utc="2026-01-01T00:00:00+00:00",
            runtime_version="b10331",
            catalog_version="2026-08-08",
            prompt_version=PROMPT_VERSION,
            served_model_id="m",
        ),
    ).model_copy(update=overrides)
    save_local_model_settings(settings_path, settings)
    return model


def test_an_unconfigured_install_is_healthy_and_not_in_need_of_repair(settings_path) -> None:
    health = validate_managed_configuration(settings_path)

    assert health.configured is False
    assert health.healthy is True
    assert health.repair_needed is False


def test_a_fully_configured_install_is_healthy(tmp_path, settings_path) -> None:
    configured(tmp_path, settings_path)

    health = validate_managed_configuration(settings_path, catalog_version="2026-08-08")

    assert health.healthy is True


def test_a_missing_model_file_asks_for_repair_rather_than_crashing(
    tmp_path, settings_path
) -> None:
    model = configured(tmp_path, settings_path)
    model.unlink()

    health = validate_managed_configuration(settings_path, catalog_version="2026-08-08")

    assert health.repair_needed is True
    assert "missing" in health.reason


def test_a_model_that_changed_size_asks_for_repair(tmp_path, settings_path) -> None:
    model = configured(tmp_path, settings_path)
    model.write_bytes(b"\0" * 128)

    health = validate_managed_configuration(settings_path, catalog_version="2026-08-08")

    assert health.repair_needed is True
    assert "changed" in health.reason


def test_a_missing_runtime_asks_for_repair(tmp_path, settings_path) -> None:
    configured(tmp_path, settings_path)
    (tmp_path / "llama-server").unlink()

    health = validate_managed_configuration(settings_path, catalog_version="2026-08-08")

    assert health.repair_needed is True
    assert "runner is missing" in health.reason


def test_an_unsupported_catalog_version_asks_for_repair(tmp_path, settings_path) -> None:
    configured(tmp_path, settings_path)

    health = validate_managed_configuration(settings_path, catalog_version="2099-01-01")

    assert health.repair_needed is True


def test_a_corrupt_settings_file_is_read_as_unconfigured(tmp_path) -> None:
    broken = tmp_path / "settings.json"
    broken.write_text("{not json at all")

    health = validate_managed_configuration(broken)

    assert health.configured is False
    assert health.healthy is True
