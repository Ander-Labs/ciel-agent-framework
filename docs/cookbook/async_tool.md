# Tools asíncronas

`@ciel.tool` acepta funciones `async def`; el runtime las *awaitea*
automáticamente. Úsalo para I/O (HTTP, base de datos, colas).

```python
import asyncio
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


@ciel.tool
async def slow_add(a: int, b: int) -> int:
    "Suma con un pequeño retraso simulado (I/O)."
    await asyncio.sleep(0.01)
    return a + b


class DummyProvider(ChatProvider):
    provider_name = "dummy"

    async def complete(self, request):
        tc = [{"id": "c1", "name": "slow_add", "arguments": {"a": 7, "b": 8}}]
        msg = ChatMessage(role="assistant", content="", tool_calls=tc)
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="tool_calls"),
            metadata={"tool_calls": tc},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy", provider="dummy"),)


async def main():
    agent = ciel.Agent(provider=DummyProvider(), tools=[slow_add], toolset="demo")
    # Dentro de código async usa arun (no run).
    resp = await agent.arun("Suma 7 + 8", tenant_id="acme")
    print(resp.tool_results[0].output)


asyncio.run(main())
```

Qué esperar:

```
15
```

!!! warning "run vs arun"
    `agent.run()` es sync y **lanza `RuntimeError`** si se llama dentro de un
    event loop en marcha. En código asíncrono usa siempre `await agent.arun(...)`.
