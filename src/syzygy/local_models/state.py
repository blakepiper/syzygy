"""The setup state machine (M16.1e).

Written down before the screen, for the same reason
`syzygy.domain.reading.ReadingStatus` was: a wizard whose legal moves live
only in button handlers acquires an illegal one the first time someone
adds a shortcut. Here the transitions are data, the TUI and the CLI drive
the same table, and a test can enumerate every path without rendering
anything.

    INTRO → INVENTORY → DISCOVERY → RECOMMEND → CONSENT
          → RUNTIME → MODEL → START → VERIFY → COMPLETE

Two things make this more than a straight line:

* **Discovery can skip work.** A compatible running endpoint jumps
  straight to VERIFY; a compatible binary skips RUNTIME. Those are edges
  in the table, not `if` statements in a screen.
* **Resuming revalidates.** `COMPLETE` is not a durable claim about the
  world - the binary can be deleted and the model file can rot - so
  re-entering setup always starts at INTRO and re-derives the facts. The
  persisted "last verified" record is evidence, never permission
  (M16.8d's startup check is the cheap version of the same idea).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class SetupState(StrEnum):
    INTRO = "intro"
    INVENTORY = "inventory"
    DISCOVERY = "discovery"
    RECOMMEND = "recommend"
    CONSENT = "consent"
    RUNTIME = "runtime"
    MODEL = "model"
    START = "start"
    VERIFY = "verify"
    COMPLETE = "complete"
    #: Recoverable: the failure card knows which step to return to.
    FAILED = "failed"
    #: The user backed out. Completed safe work (a downloaded file) is
    #: kept; nothing is activated.
    CANCELLED = "cancelled"


#: The forward edges. `FAILED` and `CANCELLED` are reachable from every
#: working state and are therefore not listed per-state - see
#: `can_transition`.
ALLOWED_TRANSITIONS: Final[dict[SetupState, frozenset[SetupState]]] = {
    SetupState.INTRO: frozenset({SetupState.INVENTORY}),
    SetupState.INVENTORY: frozenset({SetupState.DISCOVERY, SetupState.INTRO}),
    SetupState.DISCOVERY: frozenset(
        {
            SetupState.RECOMMEND,
            SetupState.INVENTORY,
            # A compatible endpoint is already serving a model: nothing to
            # recommend, download, or start - go straight to verification.
            SetupState.VERIFY,
        }
    ),
    SetupState.RECOMMEND: frozenset({SetupState.CONSENT, SetupState.DISCOVERY}),
    SetupState.CONSENT: frozenset(
        {
            SetupState.RUNTIME,
            # A usable llama.cpp is already installed - skip acquisition.
            SetupState.MODEL,
            SetupState.RECOMMEND,
        }
    ),
    SetupState.RUNTIME: frozenset({SetupState.MODEL, SetupState.CONSENT}),
    # Back from MODEL goes to CONSENT, not RUNTIME: re-running an install
    # that already succeeded is not what "back" means to anyone.
    SetupState.MODEL: frozenset({SetupState.START, SetupState.CONSENT}),
    SetupState.START: frozenset({SetupState.VERIFY, SetupState.MODEL}),
    SetupState.VERIFY: frozenset({SetupState.COMPLETE, SetupState.START}),
    SetupState.COMPLETE: frozenset(),
    # A failure card can retry the step that failed, or restart cleanly.
    SetupState.FAILED: frozenset(
        {
            SetupState.INTRO,
            SetupState.INVENTORY,
            SetupState.DISCOVERY,
            SetupState.RECOMMEND,
            SetupState.CONSENT,
            SetupState.RUNTIME,
            SetupState.MODEL,
            SetupState.START,
            SetupState.VERIFY,
            SetupState.CANCELLED,
        }
    ),
    SetupState.CANCELLED: frozenset({SetupState.INTRO}),
}

#: States from which the user is still working, so failing or cancelling
#: is always legal.
_ACTIVE_STATES: Final = frozenset(
    {
        SetupState.INTRO,
        SetupState.INVENTORY,
        SetupState.DISCOVERY,
        SetupState.RECOMMEND,
        SetupState.CONSENT,
        SetupState.RUNTIME,
        SetupState.MODEL,
        SetupState.START,
        SetupState.VERIFY,
    }
)

#: Steps that do long, cancellable work and must therefore report progress
#: (M16.9b). Anything here that renders as a frozen screen is a bug.
LONG_RUNNING_STATES: Final = frozenset(
    {
        SetupState.INVENTORY,
        SetupState.DISCOVERY,
        SetupState.RUNTIME,
        SetupState.MODEL,
        SetupState.START,
        SetupState.VERIFY,
    }
)

#: Human-readable step labels, so the wizard and `syzygy model setup-local`
#: describe the same step with the same words.
STATE_LABELS: Final[dict[SetupState, str]] = {
    SetupState.INTRO: "What this does",
    SetupState.INVENTORY: "Checking this computer",
    SetupState.DISCOVERY: "Looking for what you already have",
    SetupState.RECOMMEND: "Choosing a model",
    SetupState.CONSENT: "Review before anything is downloaded",
    SetupState.RUNTIME: "Getting the model runner",
    SetupState.MODEL: "Downloading the model",
    SetupState.START: "Starting the model",
    SetupState.VERIFY: "Checking it works with Syzygy",
    SetupState.COMPLETE: "Ready",
    SetupState.FAILED: "Setup did not finish",
    SetupState.CANCELLED: "Setup cancelled",
}


class InvalidSetupTransition(RuntimeError):
    """Raised by `assert_transition`. A bug in the caller, never something
    a user can cause by pressing keys."""


def can_transition(current: SetupState, target: SetupState) -> bool:
    if target is current:
        # Re-entering a step (a retry that re-runs discovery, say) is
        # legal and idempotent by construction.
        return current in _ACTIVE_STATES
    if target in (SetupState.FAILED, SetupState.CANCELLED):
        return current in _ACTIVE_STATES
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: SetupState, target: SetupState) -> None:
    if not can_transition(current, target):
        raise InvalidSetupTransition(f"{current.value} → {target.value} is not allowed")


def is_terminal(state: SetupState) -> bool:
    return state in (SetupState.COMPLETE, SetupState.CANCELLED)
