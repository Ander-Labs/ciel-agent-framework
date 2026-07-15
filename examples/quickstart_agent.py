"""Quickstart: tu primer agente Ciel con la API de alto nivel (@ciel.tool + ciel.Agent).

Demuestra el camino mínimo con la nueva capa Developer Experience:

  * un proveedor dummy offline (subclase de ``ciel.providers.ChatProvider``)
    que "decide" llamar a una tool de forma determinista,
  * una tool propia definida con el decorador ``@ciel.tool`` (el schema se
    infiere de los type hints + el docstring),
  * un ``ciel.Agent`` que cablea provider + tools + runtime por ti,
  * ``agent.run(...)`` síncrono que devuelve una ``ciel.AgentResponse``.

Ejecuta:
    uv run examples/quickstart_agent.py

No requiere red ni API keys: el proveedor es un stub determinista.
"""

from __future__ import annotations

import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)


# ---------------------------------------------------------------------------
# 1. Tool propia con la nueva API de alto nivel: @ciel.tool infiere el schema.
# ---------------------------------------------------------------------------
@ciel.tool
def add(a: int, b: int) -> int:
    """Suma dos enteros y devuelve el resultado."""
    return a + b


# ---------------------------------------------------------------------------
# 2. Proveedor dummy (offline): pide de forma determinista la tool "add".
# ---------------------------------------------------------------------------
class DummyProvider(ChatProvider):
    provider_name = "dummy"

    async def complete(self, request: ChatRequest) -> ChatResponse:
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
# 3. Agente de alto nivel: ciel.Agent cablea todo por ti.
# ---------------------------------------------------------------------------
def main() -> int:
    agent = ciel.Agent(provider=DummyProvider(), tools=[add], toolset="demo")

    print("[quickstart] ejecutando agent.run (offline)...")
    # tenant_id="default" es necesario: el runtime lo propaga a la auditoría.
    resp = agent.run("Suma 2 + 3", tenant_id="default")

    print(f"  finish_reason = {resp.finish_reason}")
    for tr in resp.tool_results:
        print(f"  tool={tr.name} output={tr.output}")

    ok = any(tr.output == 5 for tr in resp.tool_results)
    print(f"[quickstart] OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
