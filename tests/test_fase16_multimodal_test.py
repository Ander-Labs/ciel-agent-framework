"""Fase 16-C — native multimodal content (offline).

Verifies ``ChatMessage.content`` accepts ``str | list[dict]`` and that the
three serializers (OpenAI / Anthropic / Gemini) normalize content-parts
correctly, without any network access.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ciel.providers import AnthropicProvider, OpenAICompatibleProvider
from ciel.providers.gemini import GeminiProvider
from ciel.runtime import ChatMessage, ChatRequest


# ---------------------------------------------------------------------------
# Helper: ChatMessage.text()
# ---------------------------------------------------------------------------
def test_text_returns_str_verbatim():
    assert ChatMessage(role="user", content="hola").text() == "hola"


def test_text_concatenates_text_parts():
    content = [
        {"type": "text", "text": "primero "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": "segundo"},
    ]
    assert ChatMessage(role="user", content=content).text() == "primero segundo"


def test_text_empty_for_non_str_non_list():
    assert ChatMessage(role="user", content=None).text() == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OpenAI serializer normalizes content-parts
# ---------------------------------------------------------------------------
def _openai_request_with_messages(messages):
    req = ChatRequest(messages=messages)
    provider = OpenAICompatibleProvider(base_url="http://x/v1")

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    with patch("httpx.AsyncClient", return_value=_Client()):
        asyncio.run(provider.complete(req))
    return captured["json"]


def test_openai_serializes_str_content_as_text_part():
    payload = _openai_request_with_messages([ChatMessage(role="user", content="hi")])
    msg = payload["messages"][0]
    assert msg["content"] == [{"type": "text", "text": "hi"}]


def test_openai_serializes_multimodal_content_parts():
    content = [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,ABC"}},
    ]
    payload = _openai_request_with_messages([ChatMessage(role="user", content=content)])
    assert payload["messages"][0]["content"] == content


def test_openai_promotes_bare_text_part():
    payload = _openai_request_with_messages(
        [ChatMessage(role="user", content=[{"text": "x"}])]  # type: ignore[index]
    )
    assert payload["messages"][0]["content"] == [{"type": "text", "text": "x"}]


# ---------------------------------------------------------------------------
# Anthropic serializer -> content blocks
# ---------------------------------------------------------------------------
def _anthropic_request_with_messages(messages):
    req = ChatRequest(messages=messages)
    provider = AnthropicProvider(api_key="fake")

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}], "id": "1", "role": "assistant"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    with patch("httpx.AsyncClient", return_value=_Client()):
        asyncio.run(provider.complete(req))
    return captured["json"]


def test_anthropic_serializes_str_as_text_block():
    payload = _anthropic_request_with_messages([ChatMessage(role="user", content="hi")])
    assert payload["messages"][0]["content"] == [{"type": "text", "text": "hi"}]


def test_anthropic_serializes_image_url_as_base64_block():
    data_url = "data:image/png;base64,ABCDEF"
    content = [
        {"type": "text", "text": "what is this"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    payload = _anthropic_request_with_messages([ChatMessage(role="user", content=content)])
    blocks = payload["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "what is this"}
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "ABCDEF"}


def test_anthropic_skips_non_image_parts():
    content = [
        {"type": "text", "text": "only text"},
        {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},  # not a data URL
    ]
    payload = _anthropic_request_with_messages([ChatMessage(role="user", content=content)])
    blocks = payload["messages"][0]["content"]
    assert blocks == [{"type": "text", "text": "only text"}]


# ---------------------------------------------------------------------------
# Gemini serializer -> parts
# ---------------------------------------------------------------------------
def test_gemini_serializes_str_as_text_part():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            return _Resp()

    g = GeminiProvider(api_key="fake", client=_Client())
    out = asyncio.run(g.complete(ChatRequest(messages=[ChatMessage(role="user", content="hi")])))
    # round-trip text preserved
    assert out.choice.message.text() == "ok"


def test_gemini_serializes_image_url_as_inline_data():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    captured = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    data_url = "data:image/png;base64,Zm9v"
    content = [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    g = GeminiProvider(api_key="fake", client=_Client())
    asyncio.run(g.complete(ChatRequest(messages=[ChatMessage(role="user", content=content)])))
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0] == {"text": "describe"}
    assert parts[1] == {"inline_data": {"mime_type": "image/png", "data": "Zm9v"}}


def test_gemini_skips_non_image_parts():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    captured = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    content = [
        {"type": "text", "text": "only text"},
        {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
    ]
    g = GeminiProvider(api_key="fake", client=_Client())
    asyncio.run(g.complete(ChatRequest(messages=[ChatMessage(role="user", content=content)])))
    assert captured["json"]["contents"][0]["parts"] == [{"text": "only text"}]
