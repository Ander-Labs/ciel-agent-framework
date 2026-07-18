"""Fase 16-A — LiteLLM meta-provider (offline).

Covers the offline-safe contract: without the ``litellm`` extra the provider
is never imported at module load, construction raises a clear ProviderError,
and the default registry stays clean. With a mocked ``litellm`` module we
verify the ChatProvider contract (complete/stream/models) and Router fallback.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ciel.common import ProviderError
from ciel.providers import LiteLLMProvider, ProviderFactory
from ciel.providers import _normalize_content_parts
from ciel.providers.litellm import _build_litellm_messages
from ciel.runtime import ChatMessage, ChatRequest
from ciel.runtime.tools import ContentPart


# ---------------------------------------------------------------------------
# Offline-safe absence of the extra
# ---------------------------------------------------------------------------
def test_litellm_not_imported_without_extra():
    # The optional 'litellm' package is not installed in the test environment;
    # the core providers module must still import cleanly.
    import importlib.util

    assert importlib.util.find_spec("litellm") is None
    import ciel.providers  # must not raise (offline-safe import)


def test_litellm_provider_construction_requires_extra():
    # Without the extra, the lazy import inside the class raises ProviderError.
    from ciel.providers.litellm import LiteLLMProvider as Real

    with patch("ciel.providers.litellm._import_litellm", side_effect=ImportError("no litellm")):
        with pytest.raises(ProviderError):
            Real(model="gpt-4o-mini")


def test_default_registry_excludes_litellm_without_extra():
    from ciel.plugins import default_registry

    providers = set(default_registry().list_providers())
    assert "litellm" not in providers
    assert {"openai", "anthropic", "gemini"}.issubset(providers)


def test_factory_litellm_requires_extra():
    from ciel.providers import ProviderConfig

    cfg = ProviderConfig(name="litellm", base_url="", api_key="x", default_model="gpt-4o-mini")
    with patch("ciel.providers.litellm._import_litellm", side_effect=ImportError("no litellm")):
        with pytest.raises(ProviderError):
            ProviderFactory.from_config(cfg)


# ---------------------------------------------------------------------------
# With a mocked litellm module: contract + Router fallback
# ---------------------------------------------------------------------------
def _fake_litellm_module():
    """Build a fake ``litellm`` module exposing acompletion/Router."""

    async def acompletion(*args, **kwargs):
        choice = SimpleNamespace(
            message=SimpleNamespace(role="assistant", content="respuesta", name=None),
            finish_reason="stop",
        )
        return SimpleNamespace(choices=[choice], usage={"total_tokens": 3})

    class _Router:
        def __init__(self, model_list):
            self._entries = model_list

        async def acompletion(self, *args, **kwargs):
            return await acompletion(*args, **kwargs)

        def get_model_names(self):
            return [e["litellm_params"]["model"] for e in self._entries]

    fake = SimpleNamespace(acompletion=acompletion, Router=_Router)
    return fake


def test_litellm_complete_contract():
    with patch("ciel.providers.litellm._import_litellm", return_value=_fake_litellm_module()):
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="k")
        out = asyncio.run(
            provider.complete(ChatRequest(messages=[ChatMessage(role="user", content="hola")]))
        )
        assert out.choice.message.text() == "respuesta"
        assert out.metadata["provider"] == "litellm"


def test_litellm_stream_contract():
    async def _fake_stream(*args, **kwargs):
        for piece in ["ho", "la"]:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=piece), finish_reason=None)]
            )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason="stop")]
        )

    fake = _fake_litellm_module()
    fake.acompletion = _fake_stream  # type: ignore[attr-defined]
    with patch("ciel.providers.litellm._import_litellm", return_value=fake):
        provider = LiteLLMProvider(model="gpt-4o-mini")
        chunks = asyncio.run(
            provider.stream(ChatRequest(messages=[ChatMessage(role="user", content="hi")]))
        )
        assert len(chunks) >= 1
        assert chunks[-1].choice.message.text() == "hola"


def test_litellm_models_with_router():
    fake = _fake_litellm_module()
    with patch("ciel.providers.litellm._import_litellm", return_value=fake):
        provider = LiteLLMProvider(
            model="primary", models=["openai/gpt-4o", "anthropic/claude-3-5"]
        )
        infos = asyncio.run(provider.models())
        ids = {i.id for i in infos}
        assert {"openai/gpt-4o", "anthropic/claude-3-5"}.issubset(ids)


def test_litellm_multimodal_forwarded():
    captured = {}

    async def _capture(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        choice = SimpleNamespace(
            message=SimpleNamespace(role="assistant", content="ok", name=None),
            finish_reason="stop",
        )
        return SimpleNamespace(choices=[choice], usage=None)

    fake = _fake_litellm_module()
    fake.acompletion = _capture  # type: ignore[attr-defined]
    with patch("ciel.providers.litellm._import_litellm", return_value=fake):
        provider = LiteLLMProvider(model="gpt-4o-mini")
        content: list[ContentPart] = [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,XYZ"}},
        ]
        asyncio.run(
            provider.complete(ChatRequest(messages=[ChatMessage(role="user", content=content)]))
        )
        sent = captured["messages"][0]["content"]
        assert sent == content


def test_normalize_content_parts_roundtrip():
    assert _normalize_content_parts("hi") == [{"type": "text", "text": "hi"}]
    parts = [{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": "u"}}]
    assert _build_litellm_messages(ChatRequest(messages=[ChatMessage(role="user", content=parts)]))[0]["content"] == parts
