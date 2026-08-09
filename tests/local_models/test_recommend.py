"""Recommendation is explainable and stable (M16.3e)."""

from __future__ import annotations

from syzygy.local_models.catalog import ModelCatalog, load_catalog
from syzygy.local_models.contracts import FitVerdict, ModelTier
from syzygy.local_models.inventory import collect_inventory
from syzygy.local_models.recommend import estimate_all, recommend

from .machines import linux_cpu_probe, macos_arm_probe
from .test_fit import machine

GIB = 1024**3


def test_a_large_machine_gets_the_recommended_tier() -> None:
    result = recommend(machine(total_ram=64 * GIB))

    assert result.artifact is not None
    assert result.artifact.tier is ModelTier.RECOMMENDED
    assert result.fit is not None and result.fit.verdict is FitVerdict.COMFORTABLE


def test_syzygy_never_upgrades_to_the_higher_quality_tier_on_its_own() -> None:
    result = recommend(machine(total_ram=256 * GIB))

    assert result.artifact is not None
    assert result.artifact.tier is ModelTier.RECOMMENDED
    # It is still offered - just not chosen for you.
    assert any(
        artifact.tier is ModelTier.HIGHER_QUALITY for artifact, _fit in result.alternatives
    )


def test_a_small_machine_is_downgraded_to_the_faster_tier() -> None:
    # 10 GB installed leaves a 7 GB budget after the reserve; the
    # recommended tier needs about 7.7 GB, so it cannot be offered.
    result = recommend(machine(total_ram=10 * GIB))

    assert result.artifact is not None
    assert result.artifact.tier is ModelTier.FASTER


def test_a_machine_that_fits_nothing_gets_no_recommendation_but_an_explanation() -> None:
    result = recommend(machine(total_ram=4 * GIB))

    assert result.artifact is None
    assert result.confidence == "low"
    assert "smallest" in result.rationale


def test_a_full_disk_is_explained_as_a_disk_problem() -> None:
    result = recommend(machine(total_ram=64 * GIB, free_disk=1 * GIB))

    assert result.artifact is None
    assert "disk space" in result.rationale


def test_options_that_do_not_fit_stay_visible_with_their_reason() -> None:
    result = recommend(machine(total_ram=10 * GIB))
    verdicts = {artifact.id: fit.verdict for artifact, fit in result.alternatives}

    assert verdicts  # nothing is hidden
    for artifact, fit in result.alternatives:
        assert fit.reason
        assert artifact.display_name


def test_alternatives_are_always_in_tier_order() -> None:
    estimates = estimate_all(machine(total_ram=64 * GIB))
    tiers = [artifact.tier for artifact, _fit in estimates]

    assert tiers == [ModelTier.FASTER, ModelTier.RECOMMENDED, ModelTier.HIGHER_QUALITY]


def test_the_same_machine_always_gets_the_same_recommendation() -> None:
    inventory = machine(total_ram=32 * GIB)
    first = recommend(inventory)
    second = recommend(inventory)

    assert first.artifact is not None and second.artifact is not None
    assert first.artifact.id == second.artifact.id
    assert first.rationale == second.rationale
    assert [pair[0].id for pair in first.alternatives] == [
        pair[0].id for pair in second.alternatives
    ]


def test_confidence_is_capped_at_medium_without_evaluation_evidence() -> None:
    """Everything in the shipped catalog is `provisional`, so no
    recommendation may claim `high` confidence yet - and the rationale
    says why in the user's own terms."""
    result = recommend(machine(total_ram=64 * GIB))

    assert result.confidence == "medium"
    assert "not yet measured" in result.rationale


def test_confidence_drops_to_low_when_machine_facts_were_inferred() -> None:
    result = recommend(machine(total_ram=64 * GIB, ram_inferred=True))

    assert result.confidence == "low"
    assert "inferred" in result.rationale


def test_a_tight_fit_says_so_in_plain_language() -> None:
    # Chosen so that even the smallest option only just fits: 8.5 GB
    # installed leaves a 5.5 GB budget, and the faster tier needs 4.6 GB.
    result = recommend(machine(total_ram=(17 * GIB) // 2))

    assert result.artifact is not None
    assert result.artifact.tier is ModelTier.FASTER
    assert result.fit is not None and result.fit.verdict is FitVerdict.TIGHT
    assert "without much room to spare" in result.rationale
    assert result.confidence == "low"


def test_a_catalog_with_no_recommended_tier_falls_back_to_faster() -> None:
    catalog = load_catalog()
    trimmed = ModelCatalog(
        schema_name=catalog.schema_name,
        catalog_version=catalog.catalog_version,
        profile_context_tokens=catalog.profile_context_tokens,
        artifacts=tuple(
            entry for entry in catalog.artifacts if entry.tier is not ModelTier.RECOMMENDED
        ),
    )

    result = recommend(machine(total_ram=64 * GIB), trimmed)

    assert result.artifact is not None
    assert result.artifact.tier is ModelTier.FASTER


def test_real_machine_fixtures_produce_a_coherent_recommendation() -> None:
    """End to end over the captured fixtures: a rationale always exists,
    and a chosen artifact always comes with the estimate that justified
    it."""
    for probe in (linux_cpu_probe(), macos_arm_probe()):
        result = recommend(collect_inventory(probe))

        assert result.rationale
        if result.artifact is None:
            assert result.fit is None
        else:
            assert result.fit is not None
            assert result.fit.artifact_id == result.artifact.id
            assert result.fit.memory_budget_bytes > 0
