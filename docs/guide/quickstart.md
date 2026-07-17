# Inicio rápido — tu primer agente en ~15 líneas

Ciel expone una **API de alto nivel** (`@ciel.tool`, `ciel.Agent`,
`ciel.Context`, `AgentResponse`) que cablea por ti el runtime, el registro de
tools y el dispatcher. Multi-tenancy y trazabilidad se conservan: el
`tenant_id` fluye desde `Agent.run()` hasta cada tool.

## Instalación

```bash
uv add mana-ciel        # o: pip install mana-ciel
                        # el import y el CLI se mantienen como `ciel`
```

!!! tip "Verifica la instalación"
    ```bash
    ciel --help
    python -c "import ciel; print(ciel.__version__)"
    ```

## Opción A — 100% offline (copiable y ejecutable)

No necesitas API keys ni red: usamos un `DummyProvider` determinista que decide
llamar a la tool `add`. Guárdalo como `primer_agente.py` y ejecútalo con
`uv run python primer_agente.py`.

```python
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b


class DummyProvider(ChatProvider):
    """Provider offline: siempre pide ejecutar add(2, 3)."""
    provider_name = "dummy"

    async def complete(self, request):
        tc = [{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 3}}]
        msg = ChatMessage(role="assistant", content="", tool_calls=tc)
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="tool_calls"),
            metadata={"tool_calls": tc},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy", provider="dummy"),)


agent = ciel.Agent(provider=DummyProvider(), tools=[add], toolset="demo")
resp = agent.run("Suma 2 + 3", tenant_id="acme")

print("finish_reason:", resp.finish_reason)
for r in resp.tool_results:
    print("tool:", r.name, "->", r.output)   # add -> 5
```

Salida esperada:

```
finish_reason: tool_calls
tool: add -> 5
```

El mismo ejemplo, ya verificado, vive en el repo:

```bash
uv run examples/quickstart_agent.py
```

## Opción B — con un provider real

Sustituye el `DummyProvider` por uno real. El resto del código no cambia.

=== "OpenAI-compatible"

    ```python
    import ciel
    from ciel.providers import OpenAICompatibleProvider

    @ciel.tool
    def add(a: int, b: int) -> int:
        "Suma dos enteros."
        return a + b

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-...",
        default_model="gpt-4o-mini",
    )
    agent = ciel.Agent(provider=provider, tools=[add], model="gpt-4o-mini")
    resp = agent.run("¿Cuánto es 2 + 3?", tenant_id="acme")
    print(resp.text)
    ```

=== "Anthropic"

    ```python
    import ciel
    from ciel.providers import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-ant-...",
                                 default_model="claude-3-5-haiku-20241022")
    agent = ciel.Agent(provider=provider, tools=[], model="claude-3-5-haiku-20241022")
    print(agent.run("Hola").text)
    ```

## `async` / `await`

Dentro de código asíncrono usa `arun` (no `run`, que lanza `RuntimeError` si hay
un event loop activo):

```python
resp = await agent.arun("Suma 2 + 3", tenant_id="acme")
print(resp.text)
```

## Siguiente paso

- [Conceptos](concepts.md) — `Agent`, `Tool`, `Context`, `AgentResponse`.
- [Tools](tools.md) — inferencia de esquema, inyección de `Context`, tools `async`.
- [Providers](providers.md) — providers incluidos y cómo crear el tuyo.
