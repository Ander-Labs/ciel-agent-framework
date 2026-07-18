# Provider real (OpenAI-compatible)

Para producción sustituye el `DummyProvider` por uno real. El resto del código
(tools, `Agent`, `AgentResponse`) no cambia.

!!! note "Requiere red y API key"
    Este ejemplo hace llamadas reales al endpoint. Configura tu clave por
    variable de entorno y **nunca** la escribas en el código fuente.

```python
import os
import ciel
from ciel.providers import OpenAICompatibleProvider


@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b


provider = OpenAICompatibleProvider(
    base_url="https://api.openai.com/v1",
    api_key=os.environ["OPENAI_API_KEY"],
    default_model="gpt-4o-mini",
)

agent = ciel.Agent(
    provider=provider,
    tools=[add],
    model="gpt-4o-mini",
    instructions="Usa la tool add cuando debas sumar.",
)

resp = agent.run("¿Cuánto es 2 + 3?", tenant_id="acme")
print("Texto:", resp.text)
print("Tools:", [(r.name, r.output) for r in resp.tool_results])
```

## Otros providers incluidos

=== "Anthropic"

    ```python
    import os
    from ciel.providers import AnthropicProvider

    provider = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        default_model="claude-3-5-haiku-20241022",
    )
    ```

=== "Endpoint self-hosted (vLLM, Ollama, etc.)"

    ```python
    from ciel.providers import OpenAICompatibleProvider

    # Cualquier servidor con API OpenAI-compatible:
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",   # p.ej. Ollama
        api_key="not-needed",
        default_model="llama3.1",
    )
    ```

=== "Azure OpenAI"

    ```python
    import os
    from ciel.providers import AzureOpenAIProvider

    provider = AzureOpenAIProvider(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version="2024-10-21",
        deployment="gpt-4o",
        default_model="gpt-4o",
    )
    ```

=== "LiteLLM (meta-provider)"

    ```bash
    pip install "mana-ciel[litellm]"
    ```

    ```python
    from ciel.providers import LiteLLMProvider

    # Con fallback/balanceo vía Router
    provider = LiteLLMProvider(
        models=["gpt-4o", "claude-3-5-sonnet", "ollama/llama3.1"],
        fallback=True,
    )
    ```

Cualquier servidor con API OpenAI-compatible funciona cambiando `base_url` y
`default_model`. También puedes dejar que `auto_provider` elija el provider por
el prefijo del modelo: `auto_provider("ollama/llama3.1")`,
`auto_provider("azure/gpt-4o")` o `auto_provider("vllm/Qwen2.5-7B")`.
