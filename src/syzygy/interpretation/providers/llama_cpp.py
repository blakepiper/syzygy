"""Local inference via an OpenAI-compatible `llama-server` endpoint
(DESIGN.md section 13.2).

Talks over plain `httpx` rather than an SDK - `llama-server`'s
`/v1/chat/completions` route is the interoperability surface DESIGN.md
section 13.2 asks for, and it needs nothing heavier than an HTTP client.
Binds to localhost by default (DESIGN.md section 28); a user pointing
Syzygy at a non-default `base_url` has opted into that themselves.
"""

from __future__ import annotations

from typing import Final

import httpx

from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.interpretation.prompts import (
    RESPONSE_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_user_prompt,
)
from syzygy.interpretation.providers.structured_output import (
    ResponseValidationError,
    parse_and_validate,
)

#: Localhost only, per DESIGN.md section 28 - a user must deliberately pass
#: a different `base_url` to send anything off-machine.
DEFAULT_BASE_URL: Final = "http://127.0.0.1:8080/v1"
DEFAULT_TIMEOUT_SECONDS: Final = 120.0


class LlamaCppProvider:
    """`InterpretationProvider` for a locally running `llama-server`."""

    provider_id = "llama_cpp"

    def __init__(
        self,
        model_id: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Only ever set in tests, to stand in for a real `llama-server`
        # (httpx.MockTransport) - production code always takes the default
        # and talks over the real network transport.
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
                # A second failure is not caught here - it propagates, the
                # reading service marks INTERPRETATION_FAILED, and the card
                # and transit snapshot are left untouched (DESIGN.md 13.4).
                return parse_and_validate(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict[str, str]]) -> str:
        response = await client.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self.model_id,
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "SyzygyDailyReading",
                        "schema": RESPONSE_JSON_SCHEMA,
                        "strict": True,
                    },
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
        return content
