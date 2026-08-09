"""Local inference via an OpenAI-compatible `llama-server` endpoint
(docs/old/DESIGN.md section 13.2).

Talks over plain `httpx` rather than an SDK - `llama-server`'s
`/v1/chat/completions` route is the interoperability surface docs/old/DESIGN.md
section 13.2 asks for, and it needs nothing heavier than an HTTP client.
Binds to localhost by default (docs/old/DESIGN.md section 28); a user pointing
Syzygy at a non-default `base_url` has opted into that themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

import httpx

from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
    OracleResult,
    SummaryResult,
)
from syzygy.interpretation.prompts import (
    ORACLE_RESPONSE_JSON_SCHEMA,
    ORACLE_SYSTEM_PROMPT,
    RESPONSE_JSON_SCHEMA,
    SUMMARY_RESPONSE_JSON_SCHEMA,
    SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_oracle_prompt,
    build_repair_prompt,
    build_summary_prompt,
    build_summary_repair_prompt,
    build_user_prompt,
)
from syzygy.interpretation.providers.structured_output import (
    ResponseValidationError,
    parse_and_validate,
    parse_summary,
)

#: Localhost only, per docs/old/DESIGN.md section 28 - a user must deliberately pass
#: a different `base_url` to send anything off-machine.
DEFAULT_BASE_URL: Final = "http://127.0.0.1:8080/v1"
DEFAULT_TIMEOUT_SECONDS: Final = 120.0

#: What a *local* model gets. Deliberately much longer than the hosted
#: default: a 4B model on a laptop's processor writes a two-register
#: reading at a few tokens a second, and a timeout that fires mid-reply
#: turns a slow machine into a broken one. Nothing is waiting on the
#: event loop while this runs (see `local_models.managed_provider`).
LOCAL_TIMEOUT_SECONDS: Final = 900.0


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

    async def interpret(
        self, context: InterpretationContext
    ) -> InterpretationResult | OracleResult:
        oracle = context.kind is InterpretationKind.ORACLE
        schema = ORACLE_RESPONSE_JSON_SCHEMA if oracle else RESPONSE_JSON_SCHEMA
        schema_name = "SyzygyOracleConsultation" if oracle else "SyzygyDailyReading"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": ORACLE_SYSTEM_PROMPT if oracle else SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    build_oracle_prompt(context) if oracle else build_user_prompt(context)
                ),
            },
        ]
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            raw = await self._complete(client, messages, schema=schema, schema_name=schema_name)
            try:
                return parse_and_validate(
                    raw, context=context, provider_id=self.provider_id, model_id=self.model_id
                )
            except ResponseValidationError as exc:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": build_repair_prompt(raw, str(exc))})
                raw = await self._complete(client, messages, schema=schema, schema_name=schema_name)
                # A second failure is not caught here - it propagates, the
                # reading service marks INTERPRETATION_FAILED, and the card
                # and transit snapshot are left untouched (docs/old/DESIGN.md 13.4).
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


async def probe(
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 2.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Is a `llama-server` actually listening at `base_url`?

    For `syzygy model status` (docs/old/IMPLEMENTATION_PLAN.md §7.3, M7.10) - unlike
    the hosted providers, there is no API key to check, only "is anything
    there". Any failure (connection refused, timeout, non-2xx) means no.

    Deliberately still a boolean. "Is anything there" is the whole question
    a status line asks; M16's setup wizard needs a great deal more and uses
    `probe_capabilities` below.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models")
        return response.status_code < 300
    except httpx.HTTPError:
        return False


#: The smallest schema that still proves the thing Syzygy depends on:
#: `response_format: json_schema` with `strict`, required properties, and
#: `additionalProperties: false`. A server that merely accepts the *field*
#: and then returns prose fails this, which is the point - the daily
#: reading's schema is far larger, and discovering at reading time that a
#: server ignores it is exactly the failure M16.8 exists to prevent.
CAPABILITY_PROBE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ProbeResult:
    """What an endpoint proved, as data rather than an exception.

    Every field is independently false-able: a server can list models but
    refuse chat completions, or answer chat completions and ignore
    `response_format`. The setup orchestrator needs to tell those apart to
    say anything useful, so nothing here collapses into one boolean.
    """

    base_url: str
    reachable: bool = False
    lists_models: bool = False
    chat_completions: bool = False
    json_schema_response_format: bool = False
    model_ids: tuple[str, ...] = ()
    #: HTTP status of the first request, when there was one.
    status_code: int | None = None
    #: Short, already-safe description of the first thing that went wrong.
    error: str | None = None
    #: True for 401/403 - a running server that wants a key Syzygy has not
    #: been given, which is a *configuration* problem with its own remedy,
    #: not an unreachable server.
    requires_authentication: bool = False

    @property
    def fully_capable(self) -> bool:
        return self.reachable and self.chat_completions and self.json_schema_response_format


async def probe_capabilities(
    base_url: str = DEFAULT_BASE_URL,
    *,
    model_id: str | None = None,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """Verify an OpenAI-compatible endpoint far enough to trust it (M16.8a).

    Three questions, asked in order and stopping at the first that fails:
    does `/v1/models` answer and name a model, does `/v1/chat/completions`
    answer at all, and does it honour the exact `response_format` shape
    Syzygy's providers send.

    This is transport only. It builds no Syzygy prompt, sees no
    `InterpretationContext`, and returns a plain result object - the
    orchestration that decides what to *do* about a missing capability
    lives in `syzygy.local_models`, which is where the policy belongs.
    """
    root = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            try:
                listing = await client.get(f"{root}/models")
            except httpx.HTTPError as exc:
                return ProbeResult(base_url=root, error=_transport_error(exc))

            if listing.status_code in (401, 403):
                return ProbeResult(
                    base_url=root,
                    reachable=True,
                    status_code=listing.status_code,
                    requires_authentication=True,
                    error="the server requires an API key",
                )
            if listing.status_code >= 300:
                return ProbeResult(
                    base_url=root,
                    reachable=True,
                    status_code=listing.status_code,
                    error=f"/models answered {listing.status_code}",
                )

            model_ids = _model_ids(listing)
            served = model_id or (model_ids[0] if model_ids else "local")

            try:
                completion = await client.post(
                    f"{root}/chat/completions",
                    json={
                        "model": served,
                        "messages": [
                            {
                                "role": "user",
                                "content": 'Reply with the JSON object {"ok": true}.',
                            }
                        ],
                        "max_tokens": 32,
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "SyzygyCapabilityProbe",
                                "schema": CAPABILITY_PROBE_SCHEMA,
                                "strict": True,
                            },
                        },
                    },
                )
            except httpx.HTTPError as exc:
                return ProbeResult(
                    base_url=root,
                    reachable=True,
                    lists_models=bool(model_ids),
                    model_ids=model_ids,
                    error=_transport_error(exc),
                )

            if completion.status_code >= 300:
                return ProbeResult(
                    base_url=root,
                    reachable=True,
                    lists_models=bool(model_ids),
                    model_ids=model_ids,
                    status_code=completion.status_code,
                    requires_authentication=completion.status_code in (401, 403),
                    error=f"/chat/completions answered {completion.status_code}",
                )

            content = _completion_content(completion)
            honoured = _looks_like_probe_object(content)
            return ProbeResult(
                base_url=root,
                reachable=True,
                lists_models=bool(model_ids),
                chat_completions=content is not None,
                json_schema_response_format=honoured,
                model_ids=model_ids,
                status_code=completion.status_code,
                error=(
                    None
                    if honoured
                    else "the server accepted a JSON-schema request but did not honour it"
                ),
            )
    except httpx.HTTPError as exc:  # pragma: no cover - client construction only
        return ProbeResult(base_url=root, error=_transport_error(exc))


def _transport_error(exc: httpx.HTTPError) -> str:
    """A one-line, already-safe description. `httpx` error strings can
    carry a full URL; the base URL is shown by the caller anyway, and the
    class name plus message is what actually distinguishes "refused" from
    "timed out"."""
    return f"{type(exc).__name__}: {exc}".strip()


def _model_ids(response: httpx.Response) -> tuple[str, ...]:
    try:
        payload = response.json()
    except ValueError:
        return ()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return ()
    return tuple(
        str(entry["id"]) for entry in data if isinstance(entry, dict) and entry.get("id")
    )


def _completion_content(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _looks_like_probe_object(content: str | None) -> bool:
    if content is None:
        return False
    try:
        parsed = json.loads(content.strip())
    except ValueError:
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("ok"), bool)
