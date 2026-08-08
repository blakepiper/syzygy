"""Tests for the OpenAI provider (IMPLEMENTATION_PLAN.md §7.3).

`httpx.MockTransport` stands in for `api.openai.com`, injected via the
provider's test-only `transport=` argument - no real network call.
"""

from __future__ import annotations

import json

import httpx
import pytest

from syzygy.interpretation.providers.openai import OpenAIProvider

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


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _provider(handler) -> OpenAIProvider:
    return OpenAIProvider(
        model_id="gpt-test", api_key="test-key", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_openai_provider_returns_a_valid_result(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        return _chat_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)

    assert result.provider_id == "openai"
    assert result.model_id == "gpt-test"
    assert result.prompt_version == sample_context.prompt_version
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_openai_provider_repairs_once_then_succeeds(sample_context):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _chat_response("not json at all")
        return _chat_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)
    assert calls["n"] == 2
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_openai_provider_raises_after_second_failure(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("still not json")

    with pytest.raises(json.JSONDecodeError):
        await _provider(handler).interpret(sample_context)


@pytest.mark.asyncio
async def test_openai_provider_raises_on_http_error(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(handler).interpret(sample_context)


def test_openai_provider_resolves_api_key_when_not_passed(monkeypatch):
    from syzygy.interpretation.providers import api_keys

    monkeypatch.setattr(api_keys.keyring, "get_password", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    provider = OpenAIProvider(model_id="gpt-test")
    assert provider._api_key == "from-env"
