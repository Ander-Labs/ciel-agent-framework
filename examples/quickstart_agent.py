"""Quickstart: tu primer agente Ciel funcionando 100% OFFLINE (sin red/API keys).

Demuestra el camino mínimo programático con el runtime real:

  * un proveedor dummy (subclase de ``ciel.providers.ChatProvider``) que
    "decide" llamar a una tool,
  * una tool propia registrada con su callable en un ``ToolRegistry``,
  * el dispatcher y el ``DefaultAgentRuntime`` cableados,
  * un ``run_agent_loop`` que ejecuta la tool y devuelve el resultado.

Ejecuta:
    uv run examples/quickstart_agent.py

No requiere red ni API keys: el proveedor es un stub determinista.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import (
    ChatRequest,
    ChatResponse,
    ChatChoice,
    ChatMessage,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolRegistry,
    Tool,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# 1. Proveedor dummy (offline): devuelve un tool_call determinista.
# ---------------------------------------------------------------------------
class DummyProvider(ChatProvider):
    provider_name = "dummy"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # El proveedor "simula" que quiere sumar 2 + 3 usando la tool "add".
        tool_calls = [
            {
                "id": "call_1",
                "name": "add",
                "arguments": {"a": 2, "b": 3},
            }
        ]
        message = ChatMessage(
            role="assistant",
            content="",
            tool_calls=tool_calls,
        )
        return ChatResponse(
            choice=ChatChoice(message=message, finish_reason="tool_calls"),
            metadata={"tool_calls": tool_calls},
        )

    async def stream(self, request: ChatRequest):
        return [await self.complete(request)]

    async def models(self) -> tuple[ModelInfo, ...]:
        return (ModelInfo(id="dummy", provider=self.provider_name),)


# ---------------------------------------------------------------------------
# 2. Tool propia: una suma simple. El callable recibe (context, **arguments).
# ---------------------------------------------------------------------------
async def add(*, a: int, b: int, **kwargs: Any) -> Dict[str, Any]:
    return {"result": a + b}


# ---------------------------------------------------------------------------
# 3. Cableado mínimo del runtime.
# ---------------------------------------------------------------------------
def build_runtime() -> DefaultAgentRuntime:
    # Registro de tools en un ToolRegistry (con su callable vía Tool).
    registry = ToolRegistry(default_toolset="demo")
    registry.register_tool(
        "demo",
        Tool(
            spec=ToolSpec(
                name="add",
                description="Suma dos enteros.",
                parameters={
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
            ),
            callable_=add,
        ),
    )

    # ToolProvider del core (require_tenant_on_execution=False para el demo).
    provider = ToolProvider(registry=registry, require_tenant_on_execution=False)
    dispatcher = DefaultToolDispatcher(provider=provider, default_toolset="demo")

    return DefaultAgentRuntime(
        provider=DummyProvider(),
        dispatcher=dispatcher,
        agent="quickstart-agent",
    )


async def main() -> int:
    runtime = build_runtime()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="Suma 2 + 3"),),
        tools=(),
    )

    print("[quickstart] ejecutando run_agent_loop (offline)...")
    result = await runtime.run_agent_loop(request=request, toolset="demo")

    print(f"  finish_reason = {result.response.choice.finish_reason}")
    for turn in result.loop_results:
        for tool_result in turn.tool_results:
            print(f"  tool={tool_result.name} output={tool_result.output}")

    # Verificación simple para que el script salga con código 0 si todo bien.
    ok = any(
        tr.output.get("result") == 5
        for turn in result.loop_results
        for tr in turn.tool_results
    )
    print(f"[quickstart] OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
