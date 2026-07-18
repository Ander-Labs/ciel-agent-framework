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
- `AzureOpenAIProvider` — Azure OpenAI (deployment + api-version).
- `LiteLLMProvider` — meta-provider (extra opcional `litellm`) que expone
  100+ modelos vía el contrato `ChatProvider`, con `Router` para
  fallback/balanceo (offline-safe, import diferido).

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

## Multimodal nativo

`ChatMessage.content` acepta `str | list[dict]`. Cada parte es un dict con
`type` igual a `text`, `image_url` o `input_audio`:

```python
from ciel.providers import ChatMessage

msg = ChatMessage(
    role="user",
    content=[
        {"type": "text", "text": "¿Qué hay en esta imagen?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/foto.png"}},
    ],
)
```

El helper `ChatMessage.text()` degrada un mensaje multimodal a texto
concatenado (útil para logging o modelos solo-texto):

```python
print(msg.text())   # "¿Qué hay en esta imagen?"
```

## auto_provider por prefijo de modelo

`auto_provider(model)` elige el provider adecuado a partir del nombre del
modelo, sin instanciarlo manualmente. Reconoce estos prefijos:

| Prefijo | Provider |
|---|---|
| `gpt-`, `o1`, `o3` | OpenAI |
| `claude-` | Anthropic |
| `gemini-`, `models/` | Gemini |
| `azure/` | Azure OpenAI |
| `ollama/` | Ollama local |
| `vllm/` | vLLM / TGI |

```python
from ciel.providers import auto_provider

provider = auto_provider("ollama/llama3.1")   # Ollama en localhost:11434
provider = auto_provider("azure/gpt-4o")      # Azure OpenAI
provider = auto_provider("vllm/Qwen2.5-7B")   # vLLM/TGI en localhost:8000
```

## Azure OpenAI

```python
from ciel.providers import AzureOpenAIProvider

provider = AzureOpenAIProvider(
    api_key="...",
    azure_endpoint="https://mi-recurso.openai.azure.com",
    api_version="2024-10-21",
    deployment="gpt-4o",          # deployment name en Azure
    default_model="gpt-4o",
)
```

También disponible vía `auto_provider("azure/<deployment>")`.

## Ollama (local)

```python
from ciel.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url="http://localhost:11434/v1",
    api_key="not-needed",
    default_model="llama3.1",
)
```

Equivalente con prefijo: `auto_provider("ollama/llama3.1")`.

## vLLM / TGI (local)

```python
from ciel.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url="http://localhost:8000/v1",   # configurable vía VLLM_BASE_URL
    api_key="not-needed",
    default_model="Qwen2.5-7B",
)
```

Equivalente con prefijo: `auto_provider("vllm/Qwen2.5-7B")`.

## LiteLLM (meta-provider, extra opcional)

Instala el extra `litellm` para exponer 100+ modelos (OpenAI, Anthropic,
Gemini, Bedrock, Ollama, vLLM, etc.) detrás del mismo contrato `ChatProvider`,
con `Router` para fallback y balanceo de carga:

```bash
pip install "mana-ciel[litellm]"
```

```python
from ciel.providers import LiteLLMProvider

# Un solo modelo
provider = LiteLLMProvider(model="gpt-4o")

# Varios modelos con fallback/balanceo vía Router
provider = LiteLLMProvider(
    models=["gpt-4o", "claude-3-5-sonnet", "ollama/llama3.1"],
    fallback=True,
)
```

El import de `litellm` es **diferido** (offline-safe): el objeto se construye
sin red y sin la librería instalada; `ProviderError` se lanza en ejecución si
falta el extra o la conectividad.

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
