"""Shared raw-text-to-`InterpretationResult` validation for real providers.

Every hosted/local provider gets back a string from its transport (an SDK
response object, an HTTP JSON body) and must turn it into a validated
`InterpretationResult` or raise (docs/old/DESIGN.md section 13.4). This is the one
place that logic lives, so all three real providers apply the exact same
JSON-parsing tolerance and the exact same validation rule - a provider
module itself stays pure transport, per `syzygy.interpretation.base`.

Provenance (`provider_id`, `model_id`, `prompt_version`) is never asked of
the model (see `syzygy.interpretation.prompts.PROVENANCE_FIELDS`); it is
stamped on here from the caller and the context, not parsed from the
reply.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
    OracleResult,
    SummaryResult,
)

#: Raised for both "not JSON" and "JSON but wrong shape" so callers can
#: catch one exception type when deciding whether to attempt the single
#: repair turn (docs/old/DESIGN.md section 13.4).
ResponseValidationError = (json.JSONDecodeError, ValidationError)


def _strip_markdown_fence(text: str) -> str:
    """Tolerate a fenced code block despite `SYSTEM_PROMPT` forbidding one.

    Models occasionally wrap JSON in ```json ... ``` anyway; stripping it
    here is not "accepting prose" - the content inside must still be exactly
    one JSON object, or validation below fails and the repair turn fires.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_and_validate(
    raw_text: str,
    *,
    context: InterpretationContext,
    provider_id: str,
    model_id: str,
) -> InterpretationResult | OracleResult:
    """Parse `raw_text` as the model's reply and validate it into a result.

    Raises `json.JSONDecodeError` if it is not valid JSON, or
    `pydantic.ValidationError` if it does not match `InterpretationResult`
    once the provenance fields are stamped on - both are also exposed
    together as `ResponseValidationError` for a single `except`.
    """
    payload = json.loads(_strip_markdown_fence(raw_text))
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("expected a JSON object", raw_text, 0)
    payload = {
        **payload,
        "provider_id": provider_id,
        "model_id": model_id,
        "prompt_version": context.prompt_version,
    }
    result_type = (
        OracleResult
        if context.kind in (InterpretationKind.ORACLE, InterpretationKind.I_CHING)
        else InterpretationResult
    )
    return result_type.model_validate(payload)


def parse_summary(
    raw_text: str,
    *,
    context: InterpretationContext,
    provider_id: str,
    model_id: str,
) -> SummaryResult:
    """Parse and provenance-stamp a natal/cosmos summary response."""
    payload = json.loads(_strip_markdown_fence(raw_text))
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("expected a JSON object", raw_text, 0)
    return SummaryResult.model_validate(
        {
            **payload,
            "provider_id": provider_id,
            "model_id": model_id,
            "prompt_version": context.prompt_version,
        }
    )
