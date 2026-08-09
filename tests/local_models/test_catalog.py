"""The bundled catalog and runtime manifest must be pinned (M16.3a, M16.5a).

Two halves. The first loads what actually ships and asserts the pinning
rules hold for every entry - this is the test that fails when someone
adds an artifact with a `main` branch URL. The second feeds the validator
deliberately broken input, so the rules are known to have teeth rather
than merely being present.
"""

from __future__ import annotations

import copy
from importlib import resources

import pytest
import yaml

from syzygy.local_models.catalog import (
    ALLOWED_MODEL_HOSTS,
    CatalogValidationError,
    load_catalog,
    load_runtime_manifest,
    parse_catalog,
    parse_runtime_manifest,
    select_runtime_build,
)
from syzygy.local_models.contracts import Backend, ModelTier, SupportStatus
from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS
from syzygy.local_models.inventory import collect_inventory

from .machines import linux_cpu_probe, linux_nvidia_probe, macos_arm_probe


def raw(name: str) -> dict:
    text = resources.files("syzygy.resources.local_models").joinpath(name).read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text)


# -- what actually ships -----------------------------------------------------


def test_the_bundled_catalog_loads_and_validates() -> None:
    catalog = load_catalog()

    assert catalog.artifacts
    assert catalog.profile_context_tokens == SYZYGY_CONTEXT_TOKENS


def test_every_artifact_is_pinned_to_an_immutable_revision_and_digest() -> None:
    for entry in load_catalog().artifacts:
        assert len(entry.sha256) == 64
        assert len(entry.revision) == 40
        assert entry.download_url.startswith("https://")
        # The pin has to be in the URL that is fetched, not just recorded.
        assert entry.revision in entry.download_url
        assert "/main/" not in entry.download_url
        assert entry.size_bytes > 0


def test_every_artifact_host_is_allowlisted() -> None:
    from urllib.parse import urlparse

    for entry in load_catalog().artifacts:
        assert urlparse(entry.download_url).hostname in ALLOWED_MODEL_HOSTS


def test_no_artifact_claims_full_support_without_evaluation_evidence() -> None:
    """M16.3c's gate: `supported` means the Syzygy-specific evaluation ran.

    Everything currently shipped is `provisional`, and the UI says so -
    which is the honest state until the harness in
    `syzygy.local_models.evaluation` has been run and its results
    committed.
    """
    for entry in load_catalog().artifacts:
        if entry.support_status is SupportStatus.SUPPORTED:
            assert entry.evidence_id


def test_the_three_tiers_are_each_claimed_at_most_once() -> None:
    catalog = load_catalog()
    tiers = [entry.tier for entry in catalog.artifacts if entry.tier is not None]

    assert len(tiers) == len(set(tiers))
    assert catalog.by_tier(ModelTier.RECOMMENDED) is not None


def test_memory_profiles_are_computed_at_syzygys_own_context() -> None:
    for entry in load_catalog().artifacts:
        assert entry.memory_profile.context_tokens == SYZYGY_CONTEXT_TOKENS
        assert entry.context_tokens == SYZYGY_CONTEXT_TOKENS


def test_the_runtime_manifest_pins_a_release_and_digests_every_asset() -> None:
    manifest = load_runtime_manifest()

    assert manifest.build > 0
    for build in manifest.builds:
        assert len(build.sha256) == 64
        assert build.url.startswith("https://")
        assert manifest.release_tag in build.url
        assert build.archive_format in ("tar.gz", "zip")


def test_no_package_manager_command_requests_elevation() -> None:
    for manager in load_runtime_manifest().package_managers:
        assert "sudo" not in manager.install_argv
        assert manager.install_argv[0] == manager.executable


# -- the validator has teeth -------------------------------------------------


def test_a_branch_url_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    entry = payload["artifacts"][0]
    entry["download_url"] = (
        f"https://huggingface.co/{entry['repository']}/resolve/main/{entry['filename']}"
    )

    with pytest.raises(CatalogValidationError, match="does not pin revision"):
        parse_catalog(payload)


def test_a_non_https_url_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["artifacts"][0]["download_url"] = payload["artifacts"][0]["download_url"].replace(
        "https://", "http://"
    )

    with pytest.raises(CatalogValidationError, match="not https"):
        parse_catalog(payload)


def test_an_unallowlisted_host_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    entry = payload["artifacts"][0]
    entry["download_url"] = entry["download_url"].replace(
        "huggingface.co", "models.example.invalid"
    )

    with pytest.raises(CatalogValidationError, match="not allowlisted"):
        parse_catalog(payload)


def test_a_truncated_digest_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["artifacts"][0]["sha256"] = "abc123"

    with pytest.raises(CatalogValidationError, match="hex digest"):
        parse_catalog(payload)


def test_two_artifacts_claiming_the_same_tier_are_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["artifacts"][1]["tier"] = payload["artifacts"][0]["tier"]

    with pytest.raises(CatalogValidationError, match="claimed twice"):
        parse_catalog(payload)


def test_a_retired_artifact_may_not_hold_a_tier() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["artifacts"][0]["support_status"] = "retired"

    with pytest.raises(CatalogValidationError, match="retired but still holds a tier"):
        parse_catalog(payload)


def test_a_profile_at_the_wrong_context_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["artifacts"][0]["memory_profile"]["context_tokens"] = 4096

    with pytest.raises(CatalogValidationError, match="not Syzygy's"):
        parse_catalog(payload)


def test_a_wrong_schema_name_is_rejected() -> None:
    payload = copy.deepcopy(raw("catalog.yaml"))
    payload["schema"] = "local-model-catalog-v99"

    with pytest.raises(CatalogValidationError, match="catalog schema"):
        parse_catalog(payload)


def test_a_manifest_asking_for_sudo_is_rejected() -> None:
    payload = copy.deepcopy(raw("runtimes.yaml"))
    payload["package_managers"][0]["install_argv"] = [
        payload["package_managers"][0]["executable"],
        "sudo",
        "install",
    ]

    with pytest.raises(CatalogValidationError, match="privilege elevation"):
        parse_runtime_manifest(payload)


def test_a_manifest_asset_from_the_wrong_release_is_rejected() -> None:
    payload = copy.deepcopy(raw("runtimes.yaml"))
    payload["builds"][0]["url"] = payload["builds"][0]["url"].replace(
        payload["release_tag"], "b1"
    )

    with pytest.raises(CatalogValidationError, match="does not pin"):
        parse_runtime_manifest(payload)


# -- selection ---------------------------------------------------------------


def test_apple_silicon_gets_the_metal_build() -> None:
    inventory = collect_inventory(macos_arm_probe())
    choice = select_runtime_build(inventory)

    assert choice.build is not None
    assert choice.build.backend is Backend.METAL
    assert "macos-arm64" in choice.build.asset


def test_a_cpu_only_linux_machine_gets_the_cpu_build() -> None:
    choice = select_runtime_build(collect_inventory(linux_cpu_probe()))

    assert choice.build is not None
    assert choice.build.backend is Backend.CPU


def test_linux_nvidia_without_a_reviewed_cuda_build_falls_back_and_says_why() -> None:
    """There is no allowlisted Linux CUDA archive (see `runtimes.yaml`).

    Falling back must be explicit: the user is told the processor build is
    being used, rather than silently getting one and wondering why it is
    slow.
    """
    inventory = collect_inventory(linux_nvidia_probe())
    choice = select_runtime_build(inventory)

    assert choice.build is not None
    assert choice.build.backend is Backend.CPU
    assert "cuda" in choice.reason


def test_linux_nvidia_with_vulkan_available_gets_the_vulkan_build() -> None:
    """Not CPU. There is no reviewed Linux CUDA archive, but the machine's
    Vulkan driver works on NVIDIA, and a reviewed Vulkan build exists -
    dropping to the processor there would be a real loss of speed for no
    reason."""
    probe = linux_nvidia_probe(
        which={"nvidia-smi": "/usr/bin/nvidia-smi", "vulkaninfo": "/usr/bin/vulkaninfo"}
    )
    inventory = collect_inventory(probe)
    assert inventory.best_backend is Backend.CUDA
    assert Backend.VULKAN in inventory.candidate_backends

    choice = select_runtime_build(inventory)
    assert choice.build is not None
    assert choice.build.backend is Backend.VULKAN
    assert "cuda" in choice.reason


def test_an_unknown_platform_gets_no_build_and_an_explanation() -> None:
    from .machines import make_probe

    inventory = collect_inventory(make_probe(system="Haiku", machine="ppc64"))
    choice = select_runtime_build(inventory)

    assert choice.build is None
    assert "Haiku" in choice.reason
