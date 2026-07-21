"""Tests offline del MockProvider (Fase 18).

Determinista, sin red. Valida contrato ChatProvider, modos y streaming parity.
"""

import pytest

from ciel.providers import MockProvider
from ciel.providers.auto import auto_provider
from ciel.runtime import ChatMessage, ChatRequest, ChatResponse


def _req(text: str) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content=text)])


@pytest.mark.asyncio
async def test_fixed_mode_returns_constant():
    p = MockProvider(mode="fixed", response="HOLA")
    r = await p.complete(_req("cualquier cosa"))
    assert isinstance(r, ChatResponse)
    assert r.choice.message.content == "HOLA"
    assert r.choice.finish_reason == "stop"
    assert r.metadata["provider"] == "mock"


@pytest.mark.asyncio
async def test_echo_mode_repeats_last_word():
    p = MockProvider(mode="echo")
    r = await p.complete(_req("uno dos tres"))
    assert r.choice.message.content == "tres"


@pytest.mark.asyncio
async def test_map_mode_exact_and_substring():
    p = MockProvider(mode="map", mapping={"capital de Francia": "París", "2+2": "4"})
    assert (await p.complete(_req("capital de Francia"))).choice.message.content == "París"
    # substring (case-insensitive)
    assert (await p.complete(_req("¿capital de francia?"))).choice.message.content == "París"
    # fallback a respuesta por defecto si ninguna coincide
    assert (await p.complete(_req("otra cosa"))).choice.message.content == ""


@pytest.mark.asyncio
async def test_stream_parity_returns_single_response_tuple():
    p = MockProvider(mode="fixed", response="X")
    chunks = await p.stream(_req("q"))
    assert isinstance(chunks, tuple) and len(chunks) == 1
    assert chunks[0].choice.message.content == "X"


@pytest.mark.asyncio
async def test_determinism_same_input_same_output():
    p = MockProvider(mode="map", mapping={"a": "1", "b": "2"})
    assert (await p.complete(_req("a"))).choice.message.content == "1"
    assert (await p.complete(_req("a"))).choice.message.content == "1"


@pytest.mark.asyncio
async def test_models_reports_mock():
    p = MockProvider(mode="fixed", model="mock", response="x")
    models = await p.models()
    assert models[0].id == "mock"
    assert models[0].provider == "mock"


@pytest.mark.asyncio
async def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        MockProvider(mode="nope")


def test_auto_provider_mock_echo():
    p = auto_provider("mock/echo")
    assert p.provider_name == "mock"
    assert p.mode == "echo"


def test_auto_provider_mock_default_fixed():
    p = auto_provider("mock")
    assert p.mode == "fixed"
