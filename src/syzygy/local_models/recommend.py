"""Choosing which model to propose, explainably (M16.3e).

Deterministic: the same inventory and catalog always give the same
recommendation, in the same order, with the same words. That matters more
than it sounds - a recommendation that moves between two runs on an
unchanged machine is one nobody can debug, and one the user has no reason
to trust.

The rule, in full:

* the **Recommended** tier is the default when it fits;
* if it does not, Syzygy *downgrades* to **Faster/smaller** rather than
  offering nothing;
* it never *upgrades* on its own. **Higher quality** stays a deliberate
  choice, because the cost of it not fitting is a nine-gigabyte download
  followed by a machine that swaps;
* an artifact that does not fit stays visible, disabled, with the reason
  attached. Hiding it makes the wizard look broken on a small machine;
  showing it with "needs about 11.9 GB, 7.4 GB available" does not.
"""

from __future__ import annotations

from syzygy.local_models.catalog import ModelCatalog, load_catalog
from syzygy.local_models.contracts import (
    FitEstimate,
    FitVerdict,
    MachineInventory,
    ModelArtifact,
    ModelTier,
    Recommendation,
    SupportStatus,
)
from syzygy.local_models.fit import estimate_fit

#: Presentation order for the tier list, and the order the wizard renders
#: them in. Not preference order - see `_choose`.
TIER_ORDER = (ModelTier.FASTER, ModelTier.RECOMMENDED, ModelTier.HIGHER_QUALITY)

#: Preference order when picking a default: the recommended tier first,
#: then a downgrade. `HIGHER_QUALITY` is deliberately absent.
_DEFAULT_PREFERENCE = (ModelTier.RECOMMENDED, ModelTier.FASTER)

_USABLE = (FitVerdict.COMFORTABLE, FitVerdict.TIGHT)


def estimate_all(
    inventory: MachineInventory, catalog: ModelCatalog | None = None
) -> tuple[tuple[ModelArtifact, FitEstimate], ...]:
    """Every offerable artifact with its estimate, in tier order. Includes
    the ones that do not fit - the UI needs them to show why."""
    catalog = catalog or load_catalog()
    pairs = [(artifact, estimate_fit(artifact, inventory)) for artifact in catalog.offerable]
    return tuple(sorted(pairs, key=lambda pair: _tier_position(pair[0])))


def _tier_position(artifact: ModelArtifact) -> tuple[int, str]:
    if artifact.tier is None:
        return (len(TIER_ORDER), artifact.id)
    return (TIER_ORDER.index(artifact.tier), artifact.id)


def recommend(
    inventory: MachineInventory, catalog: ModelCatalog | None = None
) -> Recommendation:
    catalog = catalog or load_catalog()
    estimates = estimate_all(inventory, catalog)
    by_id = {artifact.id: (artifact, fit) for artifact, fit in estimates}

    chosen = _choose(catalog, by_id)
    if chosen is None:
        return Recommendation(
            artifact=None,
            fit=None,
            alternatives=estimates,
            confidence="low",
            rationale=_no_fit_rationale(estimates),
        )

    artifact, fit = chosen
    alternatives = tuple(pair for pair in estimates if pair[0].id != artifact.id)
    return Recommendation(
        artifact=artifact,
        fit=fit,
        alternatives=alternatives,
        confidence=_confidence(artifact, fit),
        rationale=_rationale(artifact, fit),
    )


def _choose(
    catalog: ModelCatalog, by_id: dict[str, tuple[ModelArtifact, FitEstimate]]
) -> tuple[ModelArtifact, FitEstimate] | None:
    # Two passes, so a comfortable smaller model beats a tight larger one.
    for verdicts in ((FitVerdict.COMFORTABLE,), _USABLE):
        for tier in _DEFAULT_PREFERENCE:
            artifact = catalog.by_tier(tier)
            if artifact is None:
                continue
            pair = by_id.get(artifact.id)
            if pair is not None and pair[1].verdict in verdicts:
                return pair
    return None


def _confidence(artifact: ModelArtifact, fit: FitEstimate) -> str:
    """Three words, and each one means something specific.

    `high` requires both halves of the evidence: machine facts we measured
    rather than inferred, *and* a Syzygy-specific evaluation result for
    this artifact. A pinned, licence-reviewed model with exact memory
    arithmetic but no evaluation is `medium` - which is where the whole
    catalog sits until M16.3b's harness has been run.
    """
    if fit.provisional or fit.verdict is not FitVerdict.COMFORTABLE:
        return "low"
    if artifact.support_status is SupportStatus.SUPPORTED and artifact.evidence_id:
        return "high"
    return "medium"


def _rationale(artifact: ModelArtifact, fit: FitEstimate) -> str:
    parts = [artifact.why.strip()] if artifact.why.strip() else []
    parts.append(f"On this computer: {fit.reason}, using {_backend_words(fit)}.")
    if fit.verdict is FitVerdict.TIGHT:
        parts.append("It fits, but without much room to spare - expect it to be slow.")
    if fit.provisional:
        parts.append(
            "Some details of this computer had to be inferred, so treat the memory "
            "figures as approximate."
        )
    if artifact.support_status is SupportStatus.PROVISIONAL:
        parts.append(
            "Syzygy has pinned and licence-checked this model and knows exactly how much "
            "memory it needs, but has not yet measured how well it writes readings on "
            "hardware like yours."
        )
    return " ".join(parts)


def _backend_words(fit: FitEstimate) -> str:
    return {
        "cpu": "the processor",
        "metal": "Apple graphics acceleration",
        "cuda": "NVIDIA graphics acceleration",
        "rocm": "AMD graphics acceleration",
        "vulkan": "graphics acceleration",
        "sycl": "Intel graphics acceleration",
    }.get(fit.backend.value, fit.backend.value)


def _no_fit_rationale(estimates: tuple[tuple[ModelArtifact, FitEstimate], ...]) -> str:
    if not estimates:
        return "No models are currently offered."
    smallest = min(estimates, key=lambda pair: pair[0].size_bytes)
    artifact, fit = smallest
    if fit.verdict is FitVerdict.INSUFFICIENT_DISK:
        return (
            f"Even {artifact.display_name}, the smallest option, needs "
            f"{fit.required_disk_bytes / 1024**3:.1f} GB of free disk space. "
            "Free some space and try again."
        )
    if fit.verdict is FitVerdict.UNKNOWN:
        return (
            "Syzygy could not learn enough about this computer to promise that any "
            "model would run. You can still choose one by hand, or point Syzygy at a "
            "server you run yourself."
        )
    return (
        f"None of the models Syzygy offers fit in this computer's memory - even "
        f"{artifact.display_name}, the smallest, {fit.reason}. A server on another "
        "machine, or a hosted provider, is the way round this."
    )
