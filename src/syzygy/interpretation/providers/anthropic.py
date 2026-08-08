"""Hosted inference via the Anthropic Messages API (DESIGN.md §13.3).

Plain `httpx` against the REST endpoint, not the `anthropic` SDK, for the
same reason as `syzygy.interpretation.providers.openai`: one request, one
response, nothing an SDK gives us that a dozen lines of `httpx` don't. The
API key never touches the Syzygy database;
`syzygy.interpretation.providers.api_keys` resolves it from the OS
keyring or the `ANTHROPIC_API_KEY` environment variable.

The Messages API has no `system` role inside `messages` (unlike the
OpenAI-shaped APIs the other two providers use) - the system prompt is a
separate top-level field, so the repair turn appends an `assistant` +
`user` pair rather than a third message role.

Selecting this provider sends the interpretation context to Anthropic's
servers. Whatever surface lets a user choose a provider (M7.10's `syzygy
model configure`, later any TUI equivalent) is responsible for saying so
before the first real call - this module itself has no UI to say it from.
"""

from __future__ import annotations

from typing import Final

import httpx

from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.interpretation.prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from syzygy.interpretation.providers.api_keys import resolve_api_key
from syzygy.interpretation.providers.structured_output import (
    ResponseValidationError,
    parse_and_validate,
)

DEFAULT_BASE_URL: Final = "https://api.anthropic.com/v1"
DEFAULT_TIMEOUT_SECONDS: Final = 60.0
ANTHROPIC_VERSION: Final = "2023-06-01"
DEFAULT_MAX_OUTPUT_TOKENS: Final = 4096
ENV_VAR: Final = "ANTHROPIC_API_KEY"


class AnthropicProvider:
    """`InterpretationProvider` for Anthropic's hosted Messages API."""

    provider_id = "anthropic"

    def __init__(
        self,
        model_id: str,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_id = model_id
        self._api_key = api_key or resolve_api_key(self.provider_id, ENV_VAR)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        # Only ever set in tests, to stand in for the real API.
        self._transport = transport

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        messages: list[dict[str, str]] = [{"role": "user", "content": build_user_prompt(context)}]
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
                # (DESIGN.md §13.4).
                return parse_and_validate(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict[str, str]]) -> str:
        response = await client.post(
            f"{self._base_url}/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            json={
                "model": self.model_id,
                "max_tokens": self._max_output_tokens,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
        )
        response.raise_for_status()
        data = response.json()
        content: str = "".join(
            block["text"] for block in data["content"] if block.get("type") == "text"
        )
        return content
