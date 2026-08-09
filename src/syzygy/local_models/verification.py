"""Proving a local model actually works for Syzygy (M16.8).

A `GET /v1/models` that answers 200 tells you almost nothing. The
questions that decide whether a reading will succeed are: can this server
produce the *exact* structured output `InterpretationResult` requires, on
this model, through the same parse-and-repair path a real reading uses -
and can it do the same for the two summary schemas. So the smoke test asks
exactly those, with fixed synthetic inputs, before the provider is ever
made active.

**No side effects, by construction.** The smoke test builds its
`InterpretationContext` in this module from a fixed card taken from the
canonical deck and hard-coded placements. It opens no database, calls no
astrology engine, performs no draw, and creates no reading. The only files
it may touch are setup logs and cache.

**Activation is atomic.** The previous provider selection is captured
first; the new one is written, the smoke test runs, and on *any* failure
the previous selection is restored exactly. A partial success - chat
completions work but the schema is ignored - is a failure, and leaves the
user exactly where they were.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from syzygy.domain.astrology import NatalPlacement, RankedTransit, TransitAspect
from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationKind,
)
from syzygy.domain.tarot import TarotCard
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.prompts import (
    COSMOS_SUMMARY_PROMPT_VERSION,
    NATAL_SUMMARY_PROMPT_VERSION,
    PROMPT_VERSION,
)
from syzygy.local_models.contracts import FailureKind, RecoveryAction, SetupFailure
from syzygy.local_models.diagnostics import redact
from syzygy.local_models.settings import (
    LocalModelSettings,
    VerificationRecord,
    load_local_model_settings,
    save_local_model_settings,
)
from syzygy.sortes.deck import load_deck

#: The card the smoke test uses. Fixed, named, and *not drawn* - picking a
#: constant from the canonical deck is a lookup, not a sortes, and the
#: distinction is the whole reason this constant is written down here
#: rather than obtained from `syzygy.sortes.draw`.
SMOKE_TEST_CARD_ID = "the_fool"

#: A synthetic profile name. Deliberately not the user's: the smoke test
#: is a test of the server, and there is no reason to send a real name to
#: a model that has not been verified yet.
SMOKE_TEST_PROFILE_NAME = "Verification"


def _fixed_card() -> TarotCard:
    for card in load_deck():
        if card.id == SMOKE_TEST_CARD_ID:
            return card
    # The deck loader validates all 78 cards, so this cannot happen unless
    # the canonical id changed - in which case a clear error beats a
    # confusing schema failure later.
    raise LookupError(f"{SMOKE_TEST_CARD_ID} is not in the canonical deck")


_SUN = NatalPlacement(body="Sun", sign="Virgo", longitude=164.37, house=10)
_MOON = NatalPlacement(body="Moon", sign="Pisces", longitude=338.18, house=4)
_SATURN = NatalPlacement(body="Saturn", sign="Capricorn", longitude=280.61, house=2)

_TRANSITS = [
    RankedTransit(
        aspect=TransitAspect(
            transiting_body="Saturn",
            natal_target="Venus",
            aspect="square",
            orb_degrees=0.8,
            movement="applying",
        ),
        score=9.5,
        rank=1,
    ),
    RankedTransit(
        aspect=TransitAspect(
            transiting_body="Mars",
            natal_target="Sun",
            aspect="trine",
            orb_degrees=1.2,
            movement="separating",
        ),
        score=6.0,
        rank=2,
    ),
]


def smoke_test_contexts() -> tuple[InterpretationContext, ...]:
    """The three shapes a local model has to handle: the daily reading,
    the natal summary, and the cosmos summary. Fixed, synthetic, and
    identical on every machine and every run."""
    def context(
        kind: InterpretationKind, prompt_version: str, *, card: TarotCard | None = None
    ) -> InterpretationContext:
        return InterpretationContext(
            kind=kind,
            card=card,
            prompt_version=prompt_version,
            profile_display_name=SMOKE_TEST_PROFILE_NAME,
            consultation_local_date="2026-01-01",
            consultation_local_timestamp="2026-01-01T09:00:00",
            significant_transits=list(_TRANSITS),
            relevant_natal_placements=[_SUN, _MOON, _SATURN],
            sun_placement=_SUN,
            moon_placement=_MOON,
            ascendant_sign="Scorpio",
            # Empty on purpose. Retrieval is a separate subsystem with its
            # own tests, and a smoke test that depended on ingested PDFs
            # would fail on every install that ships citations only (M13.3).
            knowledge_chunks=[],
        )

    return (
        context(InterpretationKind.DAILY_READING, PROMPT_VERSION, card=_fixed_card()),
        context(InterpretationKind.NATAL_SUMMARY, NATAL_SUMMARY_PROMPT_VERSION),
        context(InterpretationKind.COSMOS_SUMMARY, COSMOS_SUMMARY_PROMPT_VERSION),
    )


@dataclass(frozen=True)
class CapabilityResult:
    """One capability, and what it did."""

    name: str
    passed: bool
    seconds: float
    detail: str | None = None


@dataclass(frozen=True)
class SmokeTestResult:
    capabilities: tuple[CapabilityResult, ...] = field(default_factory=tuple)
    #: The model id the server reported, for the identity check.
    served_model_id: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.capabilities) and all(item.passed for item in self.capabilities)

    @property
    def failure(self) -> SetupFailure | None:
        if self.passed:
            return None
        failed = [item for item in self.capabilities if not item.passed]
        detail = "\n".join(f"{item.name}: {item.detail or 'failed'}" for item in failed)
        return SetupFailure(
            kind=FailureKind.SMOKE_TEST_FAILED,
            message=(
                "The model started, but couldn't produce the structured reading "
                "Syzygy needs."
            ),
            detail=redact(detail),
            actions=(
                RecoveryAction.RETRY,
                RecoveryAction.CHOOSE_SMALLER,
                RecoveryAction.USE_EXISTING_SERVER,
                RecoveryAction.COPY_DIAGNOSTICS,
            ),
        )


def run_smoke_test(provider: InterpretationProvider) -> SmokeTestResult:
    """Run every capability against `provider`. Never raises.

    Each capability is timed and reported separately, so "the reading
    schema works but the summary one doesn't" is visible rather than
    collapsed into one red cross.
    """
    reading_context, natal_context, cosmos_context = smoke_test_contexts()
    results: list[CapabilityResult] = []

    results.append(
        _capability(
            "daily reading", lambda: asyncio.run(provider.interpret(reading_context))
        )
    )
    results.append(
        _capability(
            "natal summary", lambda: asyncio.run(provider.summarize(natal_context))
        )
    )
    results.append(
        _capability(
            "cosmos summary", lambda: asyncio.run(provider.summarize(cosmos_context))
        )
    )
    return SmokeTestResult(capabilities=tuple(results))


def _capability(name: str, call) -> CapabilityResult:
    started = time.monotonic()
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every failure is a report, not a crash
        return CapabilityResult(
            name=name,
            passed=False,
            seconds=time.monotonic() - started,
            detail=f"{type(exc).__name__}: {exc}",
        )
    return CapabilityResult(name=name, passed=True, seconds=time.monotonic() - started)


# -- atomic activation -------------------------------------------------------


@dataclass(frozen=True)
class ActivationOutcome:
    activated: bool
    result: SmokeTestResult
    failure: SetupFailure | None = None


def activate_after_smoke_test(
    settings_path: Path,
    *,
    provider: InterpretationProvider,
    base_url: str,
    served_model_id: str,
    runtime_version: str | None,
    artifact_id: str | None,
    catalog_version: str | None,
    model_sha256: str | None = None,
) -> ActivationOutcome:
    """Run the smoke test and, only if it passes, make this the active
    provider. Restores the previous selection on any failure (M16.8c)."""
    from syzygy.interpretation.providers.selection import (
        LLAMA_CPP_PROVIDER_ID,
        ProviderSelection,
        clear_selection,
        load_selection,
        save_selection,
    )

    previous = load_selection(settings_path)
    result = run_smoke_test(provider)

    if not result.passed:
        # Nothing was changed, but restore explicitly anyway: a future
        # caller that writes the selection before testing must not be able
        # to leave a half-applied state behind.
        _restore(settings_path, previous, save_selection, clear_selection)
        return ActivationOutcome(False, result, result.failure)

    save_selection(
        settings_path,
        ProviderSelection(
            provider_id=LLAMA_CPP_PROVIDER_ID,
            model_id=served_model_id,
            base_url=base_url,
        ),
    )

    settings = load_local_model_settings(settings_path)
    save_local_model_settings(
        settings_path,
        settings.model_copy(
            update={
                "last_verification": VerificationRecord(
                    verified_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
                    runtime_version=runtime_version,
                    artifact_id=artifact_id,
                    catalog_version=catalog_version,
                    prompt_version=PROMPT_VERSION,
                    served_model_id=served_model_id,
                    model_sha256=model_sha256,
                )
            }
        ),
    )
    return ActivationOutcome(True, result)


def _restore(settings_path: Path, previous, save_selection, clear_selection) -> None:
    if previous is None:
        clear_selection(settings_path)
    else:
        save_selection(settings_path, previous)


def needs_reverification(
    settings: LocalModelSettings, *, runtime_version: str | None, catalog_version: str | None
) -> tuple[bool, str]:
    """Has anything changed since the last successful smoke test?

    Any of the four recorded versions moving means the evidence no longer
    covers the current configuration. This is why `VerificationRecord`
    stores versions rather than a boolean: a boolean cannot answer this.
    """
    record = settings.last_verification
    if record is None:
        return True, "this setup has never been verified"
    if record.prompt_version != PROMPT_VERSION:
        return True, "Syzygy's prompts changed since the last check"
    if runtime_version is not None and record.runtime_version != runtime_version:
        return True, "the model runner changed since the last check"
    if catalog_version is not None and record.catalog_version != catalog_version:
        return True, "the model catalogue changed since the last check"
    return False, "verified"


# -- cheap startup validation (M16.8d) ---------------------------------------


@dataclass(frozen=True)
class ConfigurationHealth:
    """What `syzygy` should do about the saved local setup on startup.

    Cheap by design: existence and size, never a nine-gigabyte re-hash.
    `syzygy model local doctor --deep` is where the digest gets checked.
    """

    configured: bool
    healthy: bool
    #: One sentence for the "Repair local model" banner.
    reason: str = ""
    repair_needed: bool = False


def validate_managed_configuration(
    settings_path: Path, *, catalog_version: str | None = None
) -> ConfigurationHealth:
    """Never raises, never blocks, never starts anything.

    A broken managed configuration is a *banner*, not a crash: the ritual
    still runs on `FixtureProvider`, exactly as it does for someone who
    never set a model up.
    """
    settings = load_local_model_settings(settings_path)
    if settings.mode is None and settings.model is None:
        return ConfigurationHealth(configured=False, healthy=True, reason="no local model set up")

    model = settings.model
    if model is None:
        return ConfigurationHealth(
            configured=True,
            healthy=False,
            reason="a local model was set up, but no model file is recorded",
            repair_needed=True,
        )

    model_path = Path(model.path)
    if not model_path.exists():
        return ConfigurationHealth(
            configured=True,
            healthy=False,
            reason="the model file is missing",
            repair_needed=True,
        )
    if model.size_bytes is not None:
        try:
            actual = model_path.stat().st_size
        except OSError:
            actual = -1
        if actual != model.size_bytes:
            return ConfigurationHealth(
                configured=True,
                healthy=False,
                reason="the model file has changed since it was verified",
                repair_needed=True,
            )

    runtime = settings.runtime
    if runtime is not None and runtime.path:
        if not Path(runtime.path).exists():
            return ConfigurationHealth(
                configured=True,
                healthy=False,
                reason="the model runner is missing",
                repair_needed=True,
            )

    stale, why = needs_reverification(
        settings,
        runtime_version=runtime.version if runtime else None,
        catalog_version=catalog_version,
    )
    if stale:
        return ConfigurationHealth(
            configured=True, healthy=False, reason=why, repair_needed=True
        )
    return ConfigurationHealth(configured=True, healthy=True, reason="verified")
