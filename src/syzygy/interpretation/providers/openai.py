"""Hosted inference via the OpenAI Chat Completions API (docs/old/DESIGN.md §13.3).

Plain `httpx` against the REST endpoint, not the `openai` SDK - the wire
format is small (one request, one response, JSON in, JSON out) and this
keeps the OpenAI-compatible surface identical to
`syzygy.interpretation.providers.llama_cpp`, which talks to the same
endpoint shape on a local server. The API key never touches the Syzygy
database; `syzygy.interpretation.providers.api_keys` resolves it from the
OS keyring or the `OPENAI_API_KEY` environment variable.

Selecting this provider sends the interpretation context to OpenAI's
servers. Whatever surface lets a user choose a provider (M7.10's `syzygy
model configure`, later any TUI equivalent) is responsible for saying so
before the first real call - this module itself has no UI to say it from.
"""

from __future__ import annotations

from typing import Final

import httpx

from syzygy.domain.interpretation import InterpretationContext, InterpretationResult, SummaryResult
from syzygy.interpretation.prompts import (
    RESPONSE_JSON_SCHEMA,
    SUMMARY_RESPONSE_JSON_SCHEMA,
    SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_summary_prompt,
    build_summary_repair_prompt,
    build_user_prompt,
)
from syzygy.interpretation.providers.api_keys import resolve_api_key
from syzygy.interpretation.providers.structured_output import (
    ResponseValidationError,
    parse_and_validate,
    parse_summary,
)

DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS: Final = 60.0
ENV_VAR: Final = "OPENAI_API_KEY"


class OpenAIProvider:
    """`InterpretationProvider` for OpenAI's hosted Chat Completions API."""

    provider_id = "openai"

    def __init__(
        self,
        model_id: str,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_id = model_id
        self._api_key = api_key or resolve_api_key(self.provider_id, ENV_VAR)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Only ever set in tests, to stand in for the real API.
        self._transport = transport

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(context)},
        ]
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            raw = await self._complete(client, messages)
            try:
                return parse_and_validate(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )
            except ResponseValidationError as exc:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": build_repair_prompt(raw, str(exc))})
                raw = await self._complete(client, messages)
                # A second failure propagates: the reading service marks
                # INTERPRETATION_FAILED and leaves the card/snapshot alone
                # (docs/old/DESIGN.md §13.4).
                return parse_and_validate(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": build_summary_prompt(context)},
        ]
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            raw = await self._complete(
                client, messages, schema=SUMMARY_RESPONSE_JSON_SCHEMA, schema_name="SyzygySummary"
            )
            try:
                return parse_summary(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )
            except ResponseValidationError as exc:
                messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": build_summary_repair_prompt(raw, str(exc))},
                    ]
                )
                raw = await self._complete(
                    client,
                    messages,
                    schema=SUMMARY_RESPONSE_JSON_SCHEMA,
                    schema_name="SyzygySummary",
                )
                return parse_summary(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )

    async def _complete(
        self,
        client: httpx.AsyncClient,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, object] = RESPONSE_JSON_SCHEMA,
        schema_name: str = "SyzygyDailyReading",
    ) -> str:
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.model_id,
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
        return content
