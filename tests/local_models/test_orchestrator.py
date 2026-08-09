"""The setup session end to end, with every service faked (M16.9f).

This is the test that proves the two front ends can be thin: the whole
flow - inventory, discovery, recommendation, consent, install, download,
start, verify - runs here with no Textual, no network, no subprocess, and
no real filesystem outside `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.interpretation.providers.selection import load_selection
from syzygy.local_models.contracts import (
    Compatibility,
    FailureKind,
    RuntimeCandidate,
    RuntimeCapabilities,
    RuntimeKind,
    RuntimeSource,
    SetupFailure,
)
from syzygy.local_models.orchestrator import (
    DiscoveryReport,
    LocalSetupSession,
    SetupStepError,
)
from syzygy.local_models.settings import (
    ManagementMode,
    load_local_model_settings,
)
from syzygy.local_models.state import InvalidSetupTransition, SetupState

from .machines import linux_cpu_probe, macos_arm_probe, make_probe


def nothing_listening(candidate: RuntimeCandidate) -> RuntimeCapabilities:
    """The default for these tests: no socket is opened at all."""
    return RuntimeCapabilities(
        candidate=candidate,
        compatibility=Compatibility.UNKNOWN,
        next_action=f"Nothing answered at {candidate.locator}.",
    )


def session(local_paths, settings_path, probe=None, **kwargs) -> LocalSetupSession:
    kwargs.setdefault("endpoint_qualifier", nothing_listening)
    return LocalSetupSession(
        paths=local_paths,
        settings_path=settings_path,
        probe=probe or macos_arm_probe(),
        **kwargs,
    )


def compatible_endpoint(url: str = "http://127.0.0.1:8080/v1") -> RuntimeCapabilities:
    return RuntimeCapabilities(
        candidate=RuntimeCandidate(
            kind=RuntimeKind.ENDPOINT, source=RuntimeSource.CONVENTIONAL_PORT, locator=url
        ),
        compatibility=Compatibility.COMPATIBLE,
        next_action="ready",
        serves_http=True,
        lists_models=True,
        chat_completions=True,
        json_schema_response_format=True,
        model_ids=("already-loaded",),
    )


def compatible_binary(path: Path) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        candidate=RuntimeCandidate(
            kind=RuntimeKind.BINARY,
            source=RuntimeSource.PATH,
            locator=str(path),
            resolved_path=str(path),
        ),
        compatibility=Compatibility.COMPATIBLE,
        next_action="ready",
        version="b10331",
    )


# -- inventory and assessment ------------------------------------------------


def test_inventory_produces_an_assessment_and_a_redacted_fact_table(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)
    assessment = flow.run_inventory()

    assert flow.state is SetupState.INVENTORY
    assert assessment.headline
    assert assessment.facts
    assert flow.platform_supported is True


def test_an_unsupported_platform_is_reported_without_stopping_the_flow(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path, probe=make_probe(system="Haiku", machine="ppc64"))
    assessment = flow.run_inventory()

    assert flow.platform_supported is False
    assert "can't set this up automatically" in assessment.headline


def test_diagnostics_before_inventory_says_so_rather_than_failing(
    local_paths, settings_path
) -> None:
    assert "No machine information" in session(local_paths, settings_path).diagnostics()


def test_diagnostics_accumulate_what_setup_has_learned(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.build_recommendation()

    report = flow.diagnostics()
    assert "[machine]" in report
    assert "[discovered]" in report
    assert "[chosen model]" in report


# -- discovery ---------------------------------------------------------------


def test_endpoint_probes_are_listed_before_anything_is_contacted(
    local_paths, settings_path
) -> None:
    planned = session(local_paths, settings_path).planned_endpoint_probes()

    assert planned
    assert all("127.0.0.1" in item.locator or "[::1]" in item.locator for item in planned)


def test_a_running_compatible_endpoint_skips_straight_to_verification(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()

    flow.use_existing_endpoint(compatible_endpoint())

    assert flow.state is SetupState.VERIFY
    assert flow.external_endpoint == "http://127.0.0.1:8080/v1"
    settings = load_local_model_settings(settings_path)
    assert settings.mode is ManagementMode.EXTERNAL
    assert settings.model is not None
    assert settings.model.served_model_id == "already-loaded"


def test_an_unsuitable_endpoint_cannot_be_used(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    unsuitable = compatible_endpoint().model_copy(
        update={"compatibility": Compatibility.UNSUITABLE}
    )

    with pytest.raises(SetupStepError) as caught:
        flow.use_existing_endpoint(unsuitable)

    assert caught.value.failure.kind is FailureKind.RUNTIME_UNSUITABLE


# -- recommendation and consent ----------------------------------------------


def test_recommendation_requires_inventory_first(local_paths, settings_path) -> None:
    with pytest.raises(SetupStepError):
        session(local_paths, settings_path).build_recommendation()


def test_the_consent_receipt_lists_every_contact_and_file(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.build_recommendation()

    receipt = flow.prepare_consent()

    assert flow.state is SetupState.CONSENT
    assert receipt.total_download_bytes > 0
    assert receipt.license_id
    assert receipt.license_url.startswith("https://")
    assert "127.0.0.1" in receipt.local_port_note
    hosts = {url for url, _why in receipt.network_contacts}
    assert any("github.com" in url for url in hosts)
    assert any("huggingface.co" in url for url in hosts)
    assert any("Download" in action for action in receipt.actions)
    assert any("switch readings" in action for action in receipt.actions)


def test_an_existing_binary_removes_the_runtime_download_from_the_receipt(
    local_paths, settings_path, tmp_path
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    binary = tmp_path / "llama-server"
    binary.write_text("x")
    flow.discovery = DiscoveryReport(binaries=(compatible_binary(binary),))
    flow.state = SetupState.DISCOVERY
    flow.build_recommendation()

    receipt = flow.prepare_consent()

    assert flow.runtime_plan is None
    assert all("github.com" not in url for url, _ in receipt.network_contacts)
    assert any("already installed" in action for action in receipt.actions)


def test_choosing_a_different_tier_changes_the_plan(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    recommendation = flow.build_recommendation()
    assert recommendation.artifact is not None

    other = next(
        artifact
        for artifact, _fit in recommendation.alternatives
        if artifact.id != recommendation.artifact.id
    )
    flow.choose(other.id)
    receipt = flow.prepare_consent()

    assert flow.chosen is not None and flow.chosen.id == other.id
    assert any(other.display_name in action for action in receipt.actions)


def test_choosing_an_unknown_artifact_is_refused(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()

    with pytest.raises(SetupStepError) as caught:
        flow.choose("not-in-the-catalogue")

    assert caught.value.failure.kind is FailureKind.CATALOG_RETIRED


def test_terms_must_be_accepted_before_the_model_is_fetched(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.build_recommendation()
    flow.prepare_consent()
    flow.runtime = compatible_binary(local_paths.runtime_dir / "llama-server")
    flow.runtime_plan = None
    flow.install_runtime()

    with pytest.raises(SetupStepError) as caught:
        flow.fetch_model()

    assert caught.value.failure.kind is FailureKind.TERMS_NOT_ACCEPTED


# -- launch profile ----------------------------------------------------------


def test_the_launch_profile_uses_physical_cores_and_offloads_on_a_gpu(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()

    profile = flow.launch_profile()

    assert profile.threads == 10  # the macOS fixture's `hw.physicalcpu`
    assert profile.gpu_layers == 999  # Metal is available
    assert profile.context_tokens == 8192


def test_a_cpu_only_machine_offloads_nothing(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path, probe=linux_cpu_probe())
    flow.run_inventory()

    assert flow.launch_profile().gpu_layers == 0


# -- state machine enforcement -----------------------------------------------


def test_the_flow_cannot_skip_from_the_intro_to_starting_a_server(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)

    with pytest.raises(InvalidSetupTransition):
        flow.move_to(SetupState.START)


def test_cancelling_keeps_completed_work_and_activates_nothing(
    local_paths, settings_path
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.build_recommendation()

    flow.cancel()

    assert flow.state is SetupState.CANCELLED
    assert load_selection(settings_path) is None


def test_a_failure_is_recorded_and_recoverable(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.fail(SetupFailure(kind=FailureKind.OFFLINE, message="no network"))

    assert flow.state is SetupState.FAILED
    assert flow.failure is not None
    # Retrying returns to the step that failed.
    flow.move_to(SetupState.INVENTORY)
    assert flow.failure is None


# -- verification ------------------------------------------------------------


def test_verification_of_an_existing_endpoint_activates_the_provider(
    local_paths, settings_path, monkeypatch
) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.use_existing_endpoint(compatible_endpoint())

    monkeypatch.setattr(
        "syzygy.interpretation.providers.llama_cpp.LlamaCppProvider",
        lambda **kwargs: FixtureProvider(),
    )
    outcome = flow.verify_and_activate()

    assert outcome.activated is True
    assert flow.state is SetupState.COMPLETE
    selection = load_selection(settings_path)
    assert selection is not None and selection.provider_id == "llama_cpp"


def test_a_failing_smoke_test_leaves_the_flow_in_failed_and_nothing_active(
    local_paths, settings_path, monkeypatch
) -> None:
    from .test_verification import DeadProvider

    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.use_existing_endpoint(compatible_endpoint())

    monkeypatch.setattr(
        "syzygy.interpretation.providers.llama_cpp.LlamaCppProvider",
        lambda **kwargs: DeadProvider(),
    )
    outcome = flow.verify_and_activate()

    assert outcome.activated is False
    assert flow.state is SetupState.FAILED
    assert load_selection(settings_path) is None


def test_verification_without_a_running_model_is_refused(local_paths, settings_path) -> None:
    flow = session(local_paths, settings_path)
    flow.run_inventory()
    flow.run_discovery()
    flow.state = SetupState.START

    with pytest.raises(SetupStepError) as caught:
        flow.verify_and_activate()

    assert caught.value.failure.kind is FailureKind.PROCESS_CRASHED
