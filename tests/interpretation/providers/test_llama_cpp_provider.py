"""Tests for the local llama.cpp provider (docs/old/IMPLEMENTATION_PLAN.md §7.3).

No real server is started - `httpx.MockTransport` stands in for
`llama-server`'s `/v1/chat/completions` route (via the provider's
test-only `transport` constructor argument), so these tests exercise the
provider's own request shaping, response parsing, and single-repair-retry
behaviour (docs/old/DESIGN.md section 13.4) without a network dependency.
"""

from __future__ import annotations

import json

import httpx
import pytest

from syzygy.interpretation.providers.llama_cpp import LlamaCppProvider

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


def _provider(handler) -> LlamaCppProvider:
    return LlamaCppProvider(model_id="local-test-model", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_llama_cpp_provider_returns_a_valid_result(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"
        return _chat_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)

    assert result.provider_id == "llama_cpp"
    assert result.model_id == "local-test-model"
    assert result.prompt_version == sample_context.prompt_version
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_llama_cpp_provider_strips_a_markdown_fence(sample_context):
    fenced = "```json\n" + json.dumps(VALID_REPLY) + "\n```"

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(fenced)

    result = await _provider(handler).interpret(sample_context)
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_llama_cpp_provider_repairs_once_then_succeeds(sample_context):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _chat_response("not json at all")
        body = json.loads(request.content)
        assert body["messages"][-1]["role"] == "user"
        assert "Validation error" in body["messages"][-1]["content"]
        return _chat_response(json.dumps(VALID_REPLY))

    result = await _provider(handler).interpret(sample_context)
    assert calls["n"] == 2
    assert result.alignment_title == "A Quiet Reckoning"


@pytest.mark.asyncio
async def test_llama_cpp_provider_raises_after_second_failure(sample_context):
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("still not json")

    with pytest.raises(json.JSONDecodeError):
        await _provider(handler).interpret(sample_context)
