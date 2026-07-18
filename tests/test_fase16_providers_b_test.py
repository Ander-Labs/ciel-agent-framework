"""Fase 16-B — Azure OpenAI / Ollama / vLLM providers (offline).

All three are exercised with a mocked ``httpx.AsyncClient`` so no network is
touched. Covers the Azure deployment/api-version routing and the
OpenAI-compatible path for Ollama/vLLM through ``auto_provider``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ciel.providers.azure import AzureOpenAIProvider
from ciel.providers.auto import auto_provider
from ciel.runtime import ChatMessage, ChatRequest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_client(post_payload):
    """Return a context-manager fake whose .post returns post_payload."""

    captured = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, path, headers=None, json=None):
            captured["path"] = path
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse(post_payload)

        async def get(self, path, headers=None):
            return _FakeResponse({"data": []})

    return _Client(), captured


def test_azure_complete_routes_deployment_and_api_version():
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "hola"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 2},
    }
    client, captured = _fake_client(payload)
    provider = AzureOpenAIProvider(
        base_url="https://res.openai.azure.com",
        api_key="k",
        deployment="my-deploy",
        api_version="2024-06-01",
    )
    with patch("httpx.AsyncClient", return_value=client):
        out = asyncio.run(
            provider.complete(ChatRequest(messages=[ChatMessage(role="user", content="hi")]))
        )
    assert out.choice.message.text() == "hola"
    # Azure path must include deployment + api-version
    assert captured["path"].startswith("/openai/deployments/my-deploy/chat/completions")
    assert "api-version=2024-06-01" in captured["path"]
    # Azure uses api-key header, not Bearer.
    assert captured["headers"]["api-key"] == "k"


def test_azure_multimodal_normalized():
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {},
    }
    client, captured = _fake_client(payload)
    provider = AzureOpenAIProvider(base_url="https://res.openai.azure.com", api_key="k", deployment="d")
    content = [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": "data:x"}}]
    with patch("httpx.AsyncClient", return_value=client):
        asyncio.run(
            provider.complete(ChatRequest(messages=[ChatMessage(role="user", content=content)]))
        )
    sent = captured["json"]["messages"][0]["content"]
    assert sent == content


def test_auto_provider_ollama_uses_local_endpoint():
    p = auto_provider("ollama/llama3")
    assert p.base_url == "http://localhost:11434/v1"
    assert p.default_model == "llama3"


def test_auto_provider_vllm_uses_local_endpoint():
    p = auto_provider("vllm/mistral")
    assert p.base_url == "http://localhost:8000/v1"
    assert p.default_model == "mistral"


def test_auto_provider_azure_returns_azure_provider():
    from ciel.providers.azure import AzureOpenAIProvider

    p = auto_provider("azure/my-deploy")
    assert isinstance(p, AzureOpenAIProvider)
    assert p.deployment == "my-deploy"


def test_ollama_complete_openai_compatible():
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "resp"}, "finish_reason": "stop"}],
        "usage": {},
    }
    client, captured = _fake_client(payload)
    provider = auto_provider("ollama/llama3")
    with patch("httpx.AsyncClient", return_value=client):
        out = asyncio.run(
            provider.complete(ChatRequest(messages=[ChatMessage(role="user", content="hi")]))
        )
    assert out.choice.message.text() == "resp"
    assert captured["path"] == "/chat/completions"
    assert captured["json"]["model"] == "llama3"
