# Providers (modelos / LLMs)

Un *provider* es la conexión al modelo. La interfaz es `ciel.providers.ChatProvider`
(ABC) con tres métodos:

```python
class ChatProvider:
    provider_name: str
    async def complete(self, request: ChatRequest) -> ChatResponse: ...
    async def stream(self, request: ChatRequest): ...          # iterable de ChatResponse
    async def models(self) -> Sequence[ModelInfo]: ...
```

## Providers incluidos (builtins)

`default_registry()` de `ciel.plugins` registra automáticamente:

- `OpenAICompatibleProvider` — cualquier endpoint OpenAI-compatible (OpenAI,
  Together, Groq, vLLM, LM Studio, etc.).
- `AnthropicProvider` — Claude vía la API de Anthropic.
- `GeminiProvider` — Google AI Studio / Vertex.

Todos son **offline-safe**: si no hay red o `api_key`, `complete` lanza
`ProviderError` en tiempo de ejecución, pero el objeto se construye sin red.

## Usar un provider real

```python
from ciel.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",            # mejor vía env / SecretStore
    default_model="gpt-4o-mini",
)
```

Para Anthropic:

```python
from ciel.providers import AnthropicProvider
provider = AnthropicProvider(api_key="sk-ant-...", default_model="claude-3-5-haiku-latest")
```

Para Gemini:

```python
from ciel.providers import GeminiProvider
provider = GeminiProvider(api_key="AIza...", default_model="gemini-1.5-flash")
```

## Registrar un provider propio (manual)

Subclasa `ChatProvider` y regístralo en `ProviderRegistry`:

```python
from ciel.providers import ChatProvider, ProviderRegistry, ChatRequest, ChatResponse

class MiProvider(ChatProvider):
    provider_name = "mi-provider"
    def __init__(self, model="mi-model"):
        self.default_model = model
    async def complete(self, request):
        ...
    async def stream(self, request):
        return [await self.complete(request)]
    async def models(self):
        return []

registry = ProviderRegistry()
registry.register("mi-provider", MiProvider())
provider = registry.get("mi-provider")
```

> **Preview v0.3.0**: el descubrimiento automático por *entry points*
> (`ciel.providers`) ya está implementado en `ciel.plugins`. Pronto no hará falta
> el registro manual: instalar un paquete de terceros bastará. Ver
> [Plugins](plugins.md).
