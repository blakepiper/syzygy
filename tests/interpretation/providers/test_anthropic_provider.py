"""Tests for the Anthropic provider (docs/old/IMPLEMENTATION_PLAN.md §7.3).

`httpx.MockTransport` stands in for `api.anthropic.com`, injected via the
provider's test-only `transport=` argument - no real network call.
"""

from __future__ import annotations

import json

import httpx
import pytest

from syzygy.interpretation.providers.anthropic import AnthropicProvider

VALID_REPLY = {
    "alignment_title": "A Quiet Reckoning",
    "esoteric": {"summary": "Summary.", "body": "Body."},
    "conventional": {
        "summary": "Summary.",
        "body": "Body.",
        "watch_for": ["Something concrete."],
        "reflection": "What is asking to be named?",
    },
    "source_chunk_ids": [],
}


def _messages_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def _provider(handler) -> AnthropicProvider:
    return AnthropicProvider(
        model_id="claude-test", api_key="test-key", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_anthropic_provider_returns_a_valid_result(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        body = json.loads(request.content)
        assert body["system"]
        assert body["messages"][0]["role"] == "user"
        return _messages_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)

    assert result.provider_id == "anthropic"
    assert result.model_id == "claude-test"
    assert result.prompt_version == sample_context.prompt_version
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_anthropic_provider_repairs_once_then_succeeds(sample_context):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _messages_response("not json at all")
        body = json.loads(request.content)
        assert body["messages"][1]["role"] == "assistant"
        assert body["messages"][2]["role"] == "user"
        return _messages_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)
    assert calls["n"] == 2
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_anthropic_provider_raises_after_second_failure(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        return _messages_response("still not json")

    with pytest.raises(json.JSONDecodeError):
        await _provider(handler).interpret(sample_context)


@pytest.mark.asyncio
async def test_anthropic_provider_concatenates_multiple_text_blocks(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.dumps(VALID_REPLY)
        half = len(payload) // 2
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": payload[:half]},
                    {"type": "text", "text": payload[half:]},
                ]
            },
        )

    result = await _provider(handler).interpret(sample_context)
    assert result.alignment_title == "A Quiet Reckoning"


def test_anthropic_provider_resolves_api_key_when_not_passed(monkeypatch):
    from syzygy.interpretation.providers import api_keys

    monkeypatch.setattr(api_keys.keyring, "get_password", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    provider = AnthropicProvider(model_id="claude-test")
    assert provider._api_key == "from-env"
