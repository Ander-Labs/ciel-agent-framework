# Agente con múltiples tools

Registra varias tools en un mismo agente. El provider decide cuál llamar; Ciel
las ejecuta y expone los resultados en `resp.tool_results`.

```python
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b


@ciel.tool
def upper(text: str) -> str:
    "Convierte texto a mayúsculas."
    return text.upper()


class DummyProvider(ChatProvider):
    provider_name = "dummy"

    async def complete(self, request):
        tc = [
            {"id": "c1", "name": "add", "arguments": {"a": 2, "b": 3}},
            {"id": "c2", "name": "upper", "arguments": {"text": "hola"}},
        ]
        msg = ChatMessage(role="assistant", content="", tool_calls=tc)
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="tool_calls"),
            metadata={"tool_calls": tc},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy", provider="dummy"),)


agent = ciel.Agent(provider=DummyProvider(), tools=[add, upper], toolset="demo")
resp = agent.run("Suma y grita", tenant_id="acme")

for r in resp.tool_results:
    print(r.name, "->", r.output)
```

Qué esperar:

```
add -> 5
upper -> HOLA
```
