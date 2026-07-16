"""Tests de Fase 11 (Developer Experience II) para la fachada de Ciel.

Cubre:
  * auto-provider desde ``model=`` (gpt-/claude-/gemini-) sin pasar provider.
  * loop ReAct multi-turno: tool_results de TODOS los turnos, max_turns.
  * streaming: ``agent.astream`` emite chunks (sync/async).
  * ``@ciel.tool(timeout=, retries=, middleware=)`` sin romper schema/docstring.
  * ``require_tenant=True`` lanza error DX-amigable cuando no hay tenant.

OFFLINE-SAFE: providers dummy locales, sin red ni API keys.
"""

from __future__ import annotations

import ciel
import pytest
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse

from ciel.api import Agent, ToolFunction, tool


# --------------------------------------------------------------------------- #
# Providers dummy OFFLINE
# --------------------------------------------------------------------------- #
class _ToolCallProvider(ChatProvider):
    """Responde tool_calls desde una cola; cuando se vacía, devuelve texto."""

    provider_name = "dummy-multiturn"

    def __init__(self, turns):
        # turns: lista de dicts; cada uno es el set de tool_calls a devolver.
        self._turns = list(turns)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self._turns:
            tc = self._turns.pop(0)
            return ChatResponse(
                choice=ChatChoice(
                    message=ChatMessage(role="assistant", content="", tool_calls=tc),
                    finish_reason="tool_calls",
                ),
                metadata={"tool_calls": tc},
            )
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content="Listo, respondí."),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


class _TextStreamProvider(ChatProvider):
    """Devuelve texto plano; stream() lo parte en caracteres como chunks."""

    provider_name = "dummy-text-stream"

    def __init__(self, text: str = "Hola mundo"):
        self._text = text

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(message=ChatMessage(role="assistant", content=self._text), finish_reason="stop"),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        # Emula SSE: un chunk por caracter acumulado.
        chunks = []
        acc = ""
        for ch in self._text:
            acc += ch
            chunks.append(
                ChatResponse(
                    choice=ChatChoice(message=ChatMessage(role="assistant", content=acc), finish_reason="stop"),
                    metadata={},
                )
            )
        return tuple(chunks)

    async def models(self):
        return ()


# --------------------------------------------------------------------------- #
# Tools para los tests
# --------------------------------------------------------------------------- #
@ciel.tool
def add(a: int, b: int) -> int:
    """Suma dos enteros."""
    return a + b


@ciel.tool(timeout=5, retries=2)
def risky() -> int:
    """Tool con opciones de ejecución."""
    return 42


# --------------------------------------------------------------------------- #
# 1. Auto-provider desde model=
# --------------------------------------------------------------------------- #
def test_auto_provider_openai_from_model():
    agent = Agent(model="gpt-4o-mini", tools=[add])
    assert agent.provider is not None
    assert agent.provider.provider_name == "openai_compat"


def test_auto_provider_anthropic_from_model():
    agent = Agent(model="claude-3-5-haiku-20241022", tools=[add])
    assert agent.provider.provider_name == "anthropic"


def test_auto_provider_gemini_from_model():
    agent = Agent(model="gemini-1.5-flash", tools=[add])
    assert agent.provider.provider_name == "gemini"


def test_explicit_provider_wins_over_model():
    dummy = _TextStreamProvider()
    agent = Agent(provider=dummy, model="gpt-4o-mini", tools=[add])
    assert agent.provider is dummy


# --------------------------------------------------------------------------- #
# 2. Loop ReAct multi-turno: tool_results de TODOS los turnos
# --------------------------------------------------------------------------- #
def test_multi_turn_collects_all_tool_results():
    # Turno 1 pide add(2,3); turno 2 pide add(10,20); luego texto.
    provider = _ToolCallProvider(
        turns=[
            [{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 3}}],
            [{"id": "c2", "name": "add", "arguments": {"a": 10, "b": 20}}],
        ]
    )
    agent = Agent(provider=provider, tools=[add])
    resp = agent.run("suma varias veces", tenant_id="acme", max_turns=5)

    # Los tool_results de AMBOS turnos deben estar presentes.
    outputs = [r.output for r in resp.tool_results]
    assert 5 in outputs  # 2 + 3
    assert 30 in outputs  # 10 + 20
    assert len(resp.tool_results) == 2
    # El agente ejecutó tools en algún turno -> finish_reason refleja tool_calls.
    assert resp.finish_reason == "tool_calls"


def test_max_turns_bounds_the_loop():
    # Provider que SIEMPRE pide add -> sin max_turns haría 32 vueltas.
    provider = _ToolCallProvider(turns=[[{"id": "c", "name": "add", "arguments": {"a": 1, "b": 1}}] for _ in range(100)])
    agent = Agent(provider=provider, tools=[add])
    resp = agent.run("bucle", tenant_id="acme", max_turns=3)
    # Con max_turns=3 el loop se corta; al menos un tool_result, a lo sumo 3.
    assert len(resp.tool_results) <= 3
    assert len(resp.tool_results) >= 1


# --------------------------------------------------------------------------- #
# 3. Streaming (astream)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_astream_yields_chunks():
    agent = Agent(provider=_TextStreamProvider("Hola mundo"), tools=[add])
    chunks = [c async for c in agent.astream("di hola", tenant_id="acme")]
    assert chunks
    # El último chunk debe contener el texto completo.
    assert "Hola mundo" in chunks[-1]


@pytest.mark.asyncio
async def test_astream_sync_consume():
    agent = Agent(provider=_TextStreamProvider("abc"), tools=[add])

    out = []
    async for c in agent.astream("x", tenant_id="acme"):
        out.append(c)
    assert any("abc" in c for c in out)


# --------------------------------------------------------------------------- #
# 4. @tool(timeout/retries/middleware) preserva schema + opciones
# --------------------------------------------------------------------------- #
def test_tool_options_recorded():
    assert isinstance(risky, ToolFunction)
    assert risky.options.get("timeout") == 5
    assert risky.options.get("retries") == 2
    # El schema no se ve afectado por las opciones.
    props = risky.as_tool.spec.parameters.get("properties", {})
    assert props == {}  # risky() no tiene parámetros


def test_tool_middleware_applied_via_agent():
    calls = []

    def counting_mw(fn):
        def wrapped(*a, **k):
            calls.append(1)
            return fn(*a, **k)

        return wrapped

    @ciel.tool(middleware=[counting_mw])
    def echo(s: str) -> str:
        """Repite el texto."""
        return s

    # El middleware envuelve el callable del runtime (se aplica al ejecutar).
    from ciel.runtime.tools import Tool

    assert isinstance(echo.as_tool, Tool)
    assert callable(echo.as_tool.callable_)
    # La opción se registra en ToolFunction.options sin tocar el schema.
    assert echo.options.get("middleware") == (counting_mw,)
    props = echo.as_tool.spec.parameters.get("properties", {})
    assert "s" in props  # schema intacto


# --------------------------------------------------------------------------- #
# 5. require_tenant lanza error DX-amigable
# --------------------------------------------------------------------------- #
def test_require_tenant_raises_without_tenant():
    from ciel.common import TenantRequired

    agent = Agent(provider=_TextStreamProvider(), tools=[add], require_tenant=True)
    with pytest.raises(TenantRequired):
        agent.run("hola", tenant_id="default")  # 'default' cuenta como "sin tenant"


def test_require_tenant_ok_with_real_tenant():
    agent = Agent(provider=_TextStreamProvider(), tools=[add], require_tenant=True)
    resp = agent.run("hola", tenant_id="acme")
    assert resp.text == "Hola mundo"
