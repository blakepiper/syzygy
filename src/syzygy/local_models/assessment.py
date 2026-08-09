"""Turning an inventory into one sentence a person can act on (M16.2c).

The wizard leads with a verdict, not a spec sheet. The spec sheet is one
keypress away (`diagnostics.inventory_facts`), and the verdict has to be
honest about the difference between "we measured this" and "we guessed".

Four verdicts, and the boundaries between them are about *experience*,
not about hardware class:

    comfortable              an accelerator and enough memory: a reading
                             arrives while you are still reading the card
    possible with trade-offs it will work; expect to wait, or to use the
                             smaller model
    CPU only, slow           no usable acceleration. Honest rather than
                             discouraging - it does work
    manual setup recommended we could not learn enough, or this platform
                             is outside the validated matrix

`MANUAL_SETUP_RECOMMENDED` never means "go away": it routes to the
advanced external-server path, which is a supported outcome of setup.
"""

from __future__ import annotations

from syzygy.local_models.contracts import (
    Assessment,
    Backend,
    MachineAssessment,
    MachineInventory,
)
from syzygy.local_models.diagnostics import inventory_facts
from syzygy.local_models.fit import memory_budget

#: Below this, no catalog entry worth shipping will fit alongside an OS.
#: Stated as a budget (RAM minus the reserve), not as installed RAM.
MINIMUM_WORKABLE_BUDGET_BYTES = 3 * 1024**3

#: A budget at or above this comfortably holds the recommended tier.
COMFORTABLE_BUDGET_BYTES = 10 * 1024**3

#: Platform/architecture pairs with an automated path validated end to end
#: (M16's "supported path" section). Anything else still gets inventory,
#: discovery, and the external-server route - it just does not get a
#: confident automatic install.
VALIDATED_PLATFORMS: frozenset[tuple[str, str]] = frozenset(
    {
        ("Darwin", "arm64"),
        ("Darwin", "x86_64"),
        ("Windows", "amd64"),
        ("Windows", "x86_64"),
        ("Linux", "x86_64"),
    }
)


def platform_key(inventory: MachineInventory) -> tuple[str, str] | None:
    if not inventory.os_name.known or not inventory.architecture.known:
        return None
    return (inventory.os_name.require(), inventory.architecture.require().lower())


def is_validated_platform(inventory: MachineInventory) -> bool:
    key = platform_key(inventory)
    if key is None:
        return False
    return key in {(system, arch.lower()) for system, arch in VALIDATED_PLATFORMS}


def assess_machine(inventory: MachineInventory) -> MachineAssessment:
    facts = inventory_facts(inventory)
    budget, backend, provisional, budget_reason = memory_budget(inventory)

    if not is_validated_platform(inventory):
        key = platform_key(inventory)
        where = f"{key[0]} on {key[1]}" if key else "this system"
        return MachineAssessment(
            assessment=Assessment.MANUAL_SETUP_RECOMMENDED,
            headline="Syzygy can't set this up automatically here.",
            detail=(
                f"Automatic setup is validated on macOS, Windows, and Linux on "
                f"mainstream processors; {where} isn't one of them yet. You can still "
                "run a local model yourself and point Syzygy at it - the last step of "
                "this wizard does exactly that."
            ),
            facts=facts,
        )

    if budget is None:
        return MachineAssessment(
            assessment=Assessment.MANUAL_SETUP_RECOMMENDED,
            headline="Syzygy couldn't work out how much memory this computer has.",
            detail=(
                f"Without that, any recommendation would be a guess ({budget_reason}). "
                "You can point Syzygy at a local server you run yourself, or continue "
                "and choose a model by hand."
            ),
            facts=facts,
        )

    if budget < MINIMUM_WORKABLE_BUDGET_BYTES:
        return MachineAssessment(
            assessment=Assessment.MANUAL_SETUP_RECOMMENDED,
            headline="This computer doesn't have enough free memory for a local model.",
            detail=(
                f"After leaving room for the system, about {_gib(budget)} would be "
                "available, and the smallest model Syzygy ships needs more than that. "
                "Readings still work in demonstration mode, and a hosted provider or a "
                "server on another machine is the other way round this."
            ),
            facts=facts,
        )

    accelerated = backend is not Backend.CPU
    qualifier = " (some values were inferred, so treat this as approximate)" if provisional else ""

    if accelerated and budget >= COMFORTABLE_BUDGET_BYTES:
        return MachineAssessment(
            assessment=Assessment.COMFORTABLE,
            headline="This computer can run a local model comfortably.",
            detail=(
                f"It has graphics acceleration Syzygy can use ({backend.value}) and about "
                f"{_gib(budget)} to spend on the model{qualifier}."
            ),
            facts=facts,
        )

    if accelerated:
        return MachineAssessment(
            assessment=Assessment.POSSIBLE_WITH_TRADE_OFFS,
            headline="A local model will work here, with a smaller model.",
            detail=(
                f"There's graphics acceleration Syzygy can use ({backend.value}), but only "
                f"about {_gib(budget)} to spend, so the faster/smaller option is the one "
                f"to pick{qualifier}."
            ),
            facts=facts,
        )

    if budget >= COMFORTABLE_BUDGET_BYTES:
        return MachineAssessment(
            assessment=Assessment.CPU_SLOW,
            headline="A local model will work here, but slowly.",
            detail=(
                "Syzygy didn't find graphics acceleration it can use, so the processor "
                f"does the work. There's about {_gib(budget)} of memory to spend, which is "
                "plenty - expect a reading to take a minute or two rather than "
                f"seconds{qualifier}."
            ),
            facts=facts,
        )

    return MachineAssessment(
        assessment=Assessment.CPU_SLOW,
        headline="A local model will work here, slowly, and only a small one.",
        detail=(
            "No graphics acceleration Syzygy can use, and about "
            f"{_gib(budget)} of memory to spend. Choose the faster/smaller model and "
            f"expect to wait for a reading{qualifier}."
        ),
        facts=facts,
    )


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f} GB"
