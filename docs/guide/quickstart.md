# Quickstart — tu primer agente en <5 min (sin red)

Este ejemplo corre **100% offline**: no necesitas API keys ni conexión. Usa un
provider mock y una tool propia, y ejecuta un loop de agente con
`DefaultAgentRuntime`.

## Opción A — programático (copiable y ejecutable)

Guarda como `primer_agente.py` y corre `uv run python primer_agente.py`:

```python
from __future__ import annotations
import asyncio
from ciel.providers import ChatProvider
from ciel.runtime import (
    ChatChoice, ChatMessage, ChatRequest, ChatResponse,
    DefaultAgentRuntime, DefaultToolDispatcher, ToolProvider,
)
from ciel.runtime.tools import Tool, ToolRegistry, ToolSpec, ToolResult


# 1) Provider offline (mock): devuelve las tool_calls que le indiquemos y luego un texto.
class MockProvider(ChatProvider):
    provider_name = "mock"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # Si el usuario pide "suma", devolvemos una tool_call; si no, texto fijo.
        last = request.messages[-1].content if request.messages else ""
        if "suma" in last:
            tool_calls = [{
                "id": "call_1", "name": "sumar",
                "arguments": {"a": 2, "b": 3},
            }]
            message = ChatMessage(role="assistant", content="", tool_calls=tool_calls)
            return ChatResponse(choice=ChatChoice(message=message, finish_reason="tool_calls"), metadata={})
        return ChatResponse(
            choice=ChatChoice(message=ChatMessage(role="assistant", content="Hola, soy tu agente offline."), finish_reason="stop"),
            metadata={},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return []


# 2) Tool propia
def sumar(arguments, *, tool_call_id="", tenant_id=None) -> ToolResult:
    a, b = arguments.get("a", 0), arguments.get("b", 0)
    return ToolResult(id=tool_call_id, name="sumar", output={"result": a + b})


# 3) Ensamblar runtime
registry = ToolRegistry(default_toolset="default")
registry.register_tool("default", Tool(
    spec=ToolSpec(name="sumar", description="Suma dos números",
                  parameters={"a": {"type": "integer"}, "b": {"type": "integer"}}),
    callable_=sumar,
))
dispatcher = DefaultToolDispatcher(
    provider=ToolProvider(registry=registry, require_tenant_on_execution=False),
    default_toolset="default",
)
runtime = DefaultAgentRuntime(provider=MockProvider(), dispatcher=dispatcher)

if __name__ == "__main__":
    result = asyncio.run(runtime.run_agent_loop(
        request=ChatRequest(messages=[ChatMessage(role="user", content="haz la suma")]),
        tenant_id="default",
    ))
    print("Respuesta:", result.response.choice.message.content)
```

Salida esperada:

```
Respuesta: Hola, soy tu agente offline.
```

(El agente ejecutó `sumar(2,3)` vía el dispatcher y luego el mock cerró el loop
con el mensaje final.)

## Opción B — script de ejemplo del repo

El repo incluye un ejemplo minimalista ya verificado offline:

```bash
uv run examples/quickstart_agent.py
```

## Siguiente paso

Sustituye `MockProvider` por un provider real:

```python
from ciel.providers import OpenAICompatibleProvider
provider = OpenAICompatibleProvider(base_url="https://api.openai.com/v1",
                                    api_key="sk-...", default_model="gpt-4o-mini")
```

Ver [Providers](providers.md).
