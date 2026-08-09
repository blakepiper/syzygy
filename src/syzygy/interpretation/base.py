"""The interpretation provider boundary.

The rest of the application must not care which provider is active
(DESIGN.md section 13.1). Every provider - fixture, local llama.cpp,
OpenAI, Anthropic - implements exactly this protocol and receives exactly
an `InterpretationContext`. A provider must never be given the profile,
the database, or the astrology engine directly; if it needs a fact, that
fact belongs in the context (see `syzygy.domain.interpretation` for what
is and isn't included, and why).

Adding a new provider (e.g. a different hosted API) means writing one
class satisfying this protocol under `syzygy.interpretation.providers` and
registering it in provider configuration - it does not require touching
the context builder, the reading state machine, or the TUI.
"""

from __future__ import annotations

from typing import Protocol

from syzygy.domain.interpretation import InterpretationContext, InterpretationResult, SummaryResult


class InterpretationProvider(Protocol):
    provider_id: str
    model_id: str

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        """Produce a structured interpretation of `context`.

        Must raise rather than return a partially-valid result if the
        underlying model output cannot be validated into
        `InterpretationResult` - see DESIGN.md section 13.4 for the
        retry-once-then-fail policy, which lives in the caller (the
        reading service), not in individual providers.
        """
        ...

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        """Produce a structured natal or daily-cosmos summary."""
        ...
