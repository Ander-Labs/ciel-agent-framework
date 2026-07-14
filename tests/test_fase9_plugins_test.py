"""Fase 9 — plugin system + providers (formal tests).

Offline-safe: no network calls; Gemini is exercised with an injected mock client.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ciel.plugins import PluginRegistry, default_registry
from ciel.providers.gemini import GeminiProvider
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.tools import ToolRegistry
from ciel.runtime.tools_builtins import BUILTIN_TOOLSET, register_builtin_tools


def test_default_registry_loads_builtin_providers():
    reg = default_registry()
    providers = set(reg.list_providers())
    assert {"openai", "anthropic", "gemini"}.issubset(providers)


def test_default_registry_loads_builtin_toolset():
    reg = default_registry()
    assert "builtins" in reg.list_toolsets()
    schema = reg.get_toolset_schema("builtins")
    names = {t.name for t in schema.tools}
    assert {"echo", "datetime", "http_get", "file_read", "shell"}.issubset(names)


def test_plugin_registry_is_isolated_and_registerable():
    reg = PluginRegistry()
    reg.load_builtins()
    assert "openai" in reg.list_providers()
    # custom registration
    reg.register_provider("dummy", GeminiProvider())
    assert "dummy" in reg.list_providers()


def test_gemini_provider_constructs_offline():
    g = GeminiProvider()  # no api_key, no network
    assert g.provider_name == "gemini"
    assert g.default_model


def test_gemini_complete_requires_api_key():
    g = GeminiProvider()
    with pytest.raises(Exception):
        asyncio.run(g.complete(ChatRequest(messages=[ChatMessage(role="user", content="hi")])))


def test_gemini_complete_with_mock_client():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "hola gemini"}]}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers=None, json=None):
            return _Resp()

    g = GeminiProvider(api_key="fake", client=_Client())
    out = asyncio.run(g.complete(ChatRequest(messages=[ChatMessage(role="user", content="hi")])))
    assert isinstance(out, ChatResponse)
    assert out.choice.message.content == "hola gemini"


def test_builtin_tools_echo_and_datetime_offline():
    tr = ToolRegistry()
    register_builtin_tools(tr)
    echo = tr.get_tool("builtins", "echo")
    res = echo.callable_({"text": "hey"}, tool_call_id="1")
    assert res.output == {"echo": "hey"}
    dt = tr.get_tool("builtins", "datetime")
    res2 = dt.callable_({}, tool_call_id="2")
    assert "now" in res2.output


def test_builtin_toolset_schema_shape():
    assert BUILTIN_TOOLSET.name == "builtins"
    assert len(BUILTIN_TOOLSET.tools) == 5
