# Auto-provider y loop multi-turno (Fase 11)

Recetas OFFLINE (sin red ni API keys) para las dos mejoras de DX de la Fase 11:

1. [Auto-provider desde `model=`](#auto-provider-desde-model)
2. [Loop ReAct multi-turno con `max_turns`](#loop-react-multi-turno)

Ambas usan `DummyProvider` (subclase de `ciel.providers.ChatProvider`).

## Auto-provider desde `model=`

Ciel elige el provider y lee la API key del entorno según el id del modelo:

- `gpt-*` / `o1*` / `o3*` → OpenAI-compatible (`OPENAI_API_KEY`)
- `claude-*` → Anthropic (`ANTHROPIC_API_KEY`)
- `gemini-*` / `models/*` → Gemini (`GEMINI_API_KEY`)

```python
import ciel

@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

# Sin pasar provider: Ciel infiere OpenAI-compatible desde el id.
agent = ciel.Agent(model="gpt-4o-mini", tools=[add])
print(agent.provider.provider_name)  # "openai_compat"

# provider= explícito siempre gana sobre model=.
agent2 = ciel.Agent(provider=ciel.providers.OpenAICompatibleProvider(base_url="...", api_key="..."), model="gpt-4o-mini")
```

Si pasas `model=` sin `provider=`, Ciel construye el provider por ti. Si no pasas
ni `model=` ni `provider=`, `Agent` queda sin provider y `run()`/`arun()` lanzan
`ValueError` (igual que en Fase 10).

## Loop ReAct multi-turno

`Agent.run()` / `arun()` iteran `tool_calls → resultados` hasta que el modelo
devuelve `finish_reason == "stop"` o se alcanza `max_turns`. `AgentResponse`
expone **todos** los `tool_results` de todos los turnos.

```python
import asyncio
import ciel
from ciel.providers import ChatProvider, ChatChoice, ChatMessage, ChatRequest, ChatResponse

class ScriptedProvider(ChatProvider):
    provider_name = "scripted"
    def __init__(self, turns):
        self._turns = list(turns)
    async def complete(self, request):
        if self._turns:
            tc = self._turns.pop(0)
            return ChatResponse(
                choice=ChatChoice(message=ChatMessage(role="assistant", content="", tool_calls=tc), finish_reason="tool_calls"),
                metadata={"tool_calls": tc},
            )
        return ChatResponse(choice=ChatChoice(message=ChatMessage(role="assistant", content="Listo."), finish_reason="stop"), metadata={})
    async def stream(self, request):
        return (await self.complete(request),)
    async def models(self):
        return ()

@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

# Turno 1 pide add(2,3); turno 2 pide add(10,20); luego el modelo para.
agent = ciel.Agent(
    provider=ScriptedProvider([
        [{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 3}}],
        [{"id": "c2", "name": "add", "arguments": {"a": 10, "b": 20}}],
    ]),
    tools=[add],
)

resp = agent.run("suma varias veces", tenant_id="acme", max_turns=5)
outputs = [r.output for r in resp.tool_results]
assert outputs == [5, 30]            # resultados de AMBOS turnos
assert resp.finish_reason == "tool_calls"
```

### Streaming (`astream`)

`agent.astream(prompt)` es un async iterator sobre los tokens del provider
(SSE real para OpenAI/Anthropic/Gemini; el texto final como un chunk para
providers offline):

```python
async def main():
    agent = ciel.Agent(model="gpt-4o-mini", tools=[add])
    async for chunk in agent.astream("Cuánto es 2 + 3?", tenant_id="acme"):
        print(chunk, end="", flush=True)
```
