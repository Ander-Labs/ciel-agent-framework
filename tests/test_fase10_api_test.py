"""Tests para la fachada de API pública de Ciel (Fase 10 / v0.4.0).

Cubre ``@ciel.tool`` (inferencia de schema + Context), ``ciel.Context``,
``ciel.Agent`` (sync ``run`` / async ``arun``) y ``ciel.AgentResponse``.

OFFLINE-SAFE: los providers son subclases locales de ``ciel.providers.ChatProvider``
que no hacen ninguna llamada de red. NO se toca ningún otro archivo del repo.
"""

from __future__ import annotations

import ciel
import pytest
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.tools import Tool, ToolResult
from typing import Dict, List, Optional

from ciel.api import Agent, AgentResponse, Context, ToolFunction, tool


# --------------------------------------------------------------------------- #
# Providers dummy OFFLINE (no red)
# --------------------------------------------------------------------------- #
class DummyToolCallProvider(ChatProvider):
    """Devuelve tool_calls en la primera llamada y luego texto (finish_reason
    'stop'), simulando un modelo multi-turno que ejecuta la tool y responde.
    Si se le pasa una lista de turnos, los consume en orden (multi-turno real)."""

    provider_name = "dummy-toolcall"

    def __init__(self, tool_calls):
        # Acepta un solo set de tool_calls o una lista de turnos.
        if isinstance(tool_calls, (list, tuple)) and tool_calls and isinstance(tool_calls[0], dict):
            self._turns = [tool_calls]
        else:
            self._turns = list(tool_calls)

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
                message=ChatMessage(role="assistant", content="Listo."),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


class DummyTextProvider(ChatProvider):
    """Devuelve texto plano con finish_reason='stop' (sin tool_calls)."""

    provider_name = "dummy-text"

    def __init__(self, text: str = "Hola desde el asistente."):
        self._text = text

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=self._text),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


# --------------------------------------------------------------------------- #
# Tools locales para los tests del Agent
# --------------------------------------------------------------------------- #
@ciel.tool
def add(a: int, b: int) -> int:
    """Suma dos enteros."""
    return a + b


@ciel.tool
async def aadd(a: int, b: int) -> int:
    """Suma asíncrona de dos enteros."""
    return a + b


@ciel.tool
def get_tenant(ctx: ciel.Context) -> str:
    """Devuelve el tenant_id inyectado en el contexto."""
    return ctx.tenant_id


# --------------------------------------------------------------------------- #
# 1. Inferencia de schema para tipos simples int / str / bool
# --------------------------------------------------------------------------- #
def test_schema_inference_simple_types():
    @ciel.tool
    def simple(a: int, b: str, c: bool) -> int:
        """Función simple."""
        return 0

    params = simple.as_tool.spec.parameters
    props = params.get("properties", {})
    assert props["a"]["type"] == "integer"
    assert props["b"]["type"] == "string"
    assert props["c"]["type"] == "boolean"
    # Todos los parámetros sin default son requeridos.
    assert set(params.get("required", [])) >= {"a", "b", "c"}
    assert params.get("type") == "object"


# --------------------------------------------------------------------------- #
# 2. Inferencia de schema para tipos complejos List / Dict / Optional
# --------------------------------------------------------------------------- #
def test_schema_inference_complex_types():
    @ciel.tool
    def complex(items: List[str], mapping: Dict[str, int], maybe: Optional[int]) -> int:
        """Función con tipos complejos."""
        return 0

    params = complex.as_tool.spec.parameters
    props = params.get("properties", {})

    # List[str] -> array con items string
    assert props["items"]["type"] == "array"
    assert props["items"]["items"]["type"] == "string"

    # Dict[str, int] -> object con additionalProperties integer
    assert props["mapping"]["type"] == "object"
    assert props["mapping"]["additionalProperties"]["type"] == "integer"

    # Optional[int] -> anyOf [integer, null]
    maybe = props["maybe"]
    assert "anyOf" in maybe
    types = {sub.get("type") for sub in maybe["anyOf"]}
    assert {"integer", "null"} <= types


# --------------------------------------------------------------------------- #
# 3. Un parámetro anotado con ciel.Context se EXCLUYE del schema
# --------------------------------------------------------------------------- #
def test_context_excluded_from_schema():
    @ciel.tool
    def with_ctx(a: int, ctx: ciel.Context) -> int:
        """Tool con contexto."""
        return 0

    params = with_ctx.as_tool.spec.parameters
    props = params.get("properties", {})
    assert "ctx" not in props, "el parámetro ctx NO debe aparecer en el schema"
    assert "a" in props, "los parámetros normales sí deben aparecer"
    assert "ctx" not in params.get("required", [])


# --------------------------------------------------------------------------- #
# 4. La descripción del tool sale del docstring
# --------------------------------------------------------------------------- #
def test_description_from_docstring():
    @ciel.tool
    def documented(x: int) -> int:
        """Esta es la descripción del docstring."""
        return x

    assert "Esta es la descripción del docstring." in documented.description
    assert documented.as_tool.spec.description == documented.description


# --------------------------------------------------------------------------- #
# 5. @tool(name=..., description=...) override
# --------------------------------------------------------------------------- #
def test_tool_name_description_override():
    @ciel.tool(name="sumar", description="Suma personalizada con override.")
    def original(a: int, b: int) -> int:
        """Docstring original que debe ser ignorado."""
        return a + b

    assert original.name == "sumar"
    assert original.as_tool.spec.name == "sumar"
    assert original.description == "Suma personalizada con override."
    assert original.as_tool.spec.description == "Suma personalizada con override."
    # El override gana al docstring.
    assert "Docstring original" not in original.description


# --------------------------------------------------------------------------- #
# 6. ToolFunction sigue siendo llamable directamente
# --------------------------------------------------------------------------- #
def test_toolfunction_still_callable():
    # Llamable como función Python normal.
    assert add(2, 3) == 5
    assert add(10, -4) == 6

    # Es una ToolFunction y expone .as_tool, .name, .description.
    assert isinstance(add, ToolFunction)
    assert isinstance(add.as_tool, Tool)
    assert add.name == "add"
    assert "Suma dos enteros" in add.description
    assert add.as_tool.spec.name == "add"

    # El wrapper preserva el nombre original.
    assert add.__name__ == "add"


# --------------------------------------------------------------------------- #
# 7. Agent.run (sync) ejecuta el tool y AgentResponse.tool_results es correcto
# --------------------------------------------------------------------------- #
def test_agent_run_sync_executes_tool():
    agent = Agent(provider=DummyToolCallProvider(
        tool_calls=[{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 3}}]
    ), tools=[add])

    resp = agent.run("Cuánto es 2 + 3?", tenant_id="acme")

    # tool_results es una lista plana de ToolResult.
    assert isinstance(resp.tool_results, list)
    assert len(resp.tool_results) == 1
    result = resp.tool_results[0]
    assert isinstance(result, ToolResult)
    assert result.name == "add"
    assert result.output == 5  # 2 + 3

    # tool_calls expone el nombre solicitado por el modelo.
    assert any(call.get("name") == "add" for call in resp.tool_calls)

    # finish_reason refleja la ejecución de tools.
    assert resp.finish_reason == "tool_calls"

    # .raw es el AgentRuntimeResult crudo.
    assert isinstance(resp.raw, object)


# --------------------------------------------------------------------------- #
# 8. Agent.arun (async) es equivalente a run
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agent_arun_async_executes_tool():
    agent = Agent(provider=DummyToolCallProvider(
        tool_calls=[{"id": "c1", "name": "add", "arguments": {"a": 4, "b": 6}}]
    ), tools=[add])

    resp = await agent.arun("Cuánto es 4 + 6?", tenant_id="acme")

    assert isinstance(resp.tool_results, list)
    assert len(resp.tool_results) == 1
    assert resp.tool_results[0].output == 10  # 4 + 6
    assert any(call.get("name") == "add" for call in resp.tool_calls)
    assert resp.finish_reason == "tool_calls"


# --------------------------------------------------------------------------- #
# 9. AgentResponse.text con provider que devuelve texto (finish_reason='stop')
# --------------------------------------------------------------------------- #
def test_agent_response_text_with_stop():
    text = "La respuesta final del asistente."
    agent = Agent(provider=DummyTextProvider(text=text), tools=[add])

    resp = agent.run("Habla.", tenant_id="acme")

    assert isinstance(resp, AgentResponse)
    assert resp.text == text
    assert resp.finish_reason == "stop"
    # Sin tool_calls => tool_results vacío.
    assert resp.tool_results == []


# --------------------------------------------------------------------------- #
# 10. Context inyecta tenant_id hasta el tool
# --------------------------------------------------------------------------- #
def test_context_injects_tenant_id():
    agent = Agent(provider=DummyToolCallProvider(
        tool_calls=[{"id": "c1", "name": "get_tenant", "arguments": {}}]
    ), tools=[get_tenant])

    resp = agent.run("¿Quién soy?", tenant_id="acme")

    assert len(resp.tool_results) == 1
    # El tool devolvió ctx.tenant_id, que debe ser 'acme'.
    assert resp.tool_results[0].output == "acme"


# --------------------------------------------------------------------------- #
# 11. Tool asíncrono (@ciel.tool sobre async def) se ejecuta correctamente
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_async_tool_executes_via_runtime():
    agent = Agent(provider=DummyToolCallProvider(
        tool_calls=[{"id": "c1", "name": "aadd", "arguments": {"a": 7, "b": 8}}]
    ), tools=[aadd])

    resp = await agent.arun("Suma 7 + 8 de forma asíncrona.", tenant_id="acme")

    assert len(resp.tool_results) == 1
    # El callable async se awaiteó y devolvió el resultado.
    assert resp.tool_results[0].output == 15  # 7 + 8
    assert resp.tool_results[0].name == "aadd"


# --------------------------------------------------------------------------- #
# 12. Agent(provider=None).arun lanza ValueError
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agent_arun_no_provider_raises_valueerror():
    agent = Agent(provider=None, tools=[add])

    with pytest.raises(ValueError):
        await agent.arun("Sin provider")
