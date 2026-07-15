# Instrucciones de sistema

Pasa `instructions=` al construir el `Agent` para anteponer un *system prompt* a
cada ejecución. Ciel lo inserta como primer mensaje (`role="system"`) del
`ChatRequest`.

```python
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


class EchoSystemProvider(ChatProvider):
    """Provider offline que devuelve como texto el system prompt recibido."""
    provider_name = "dummy"

    async def complete(self, request):
        system = next((m.content for m in request.messages if m.role == "system"), "")
        msg = ChatMessage(role="assistant", content=f"[system] {system}")
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="stop"),
            metadata={},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy", provider="dummy"),)


agent = ciel.Agent(
    provider=EchoSystemProvider(),
    tools=[],
    instructions="Eres un asistente conciso que responde en español.",
)
resp = agent.run("Hola", tenant_id="acme")
print(resp.text)
```

Qué esperar:

```
[system] Eres un asistente conciso que responde en español.
```

Con un provider real, `instructions` define el comportamiento/persona del
agente y `resp.text` contiene la respuesta del modelo.
