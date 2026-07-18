# `ciel.providers` — Proveedores de modelos

Contratos y proveedores de modelos agnósticos al proveedor. Define los DTOs de
configuración (`ProviderConfig`, `ModelInfo`), el contrato `ChatProvider` y un
registro/fábrica (`ProviderRegistry`, `ProviderFactory`), junto con
implementaciones `OpenAICompatibleProvider`, `AnthropicProvider`,
`AzureOpenAIProvider` y `LiteLLMProvider`.

!!! note
    Los DTOs de solicitud/respuesta de chat (`ChatRequest`, `ChatResponse`,
    `ChatMessage`, `ChatChoice`) se definen en `ciel.runtime` y se reutilizan
    aquí.

## Contenido multimodal (`ChatMessage.content`)

Desde v0.10.0, `ChatMessage.content` es `str | list[dict[str, Any]]`:

- `str` — texto plano (comportamiento histórico, 100% compatible).
- `list[dict]` — lista de **partes de contenido** (multimodal). Cada parte es
  un dict con `"type"` y campos específicos:

  | `type`        | Campos                                                        |
  |---------------|---------------------------------------------------------------|
  | `"text"`      | `{"type": "text", "text": "..."}`                             |
  | `"image_url"` | `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` |
  | `"input_audio"` | `{"type": "input_audio", "input_audio": {"data": "...", "format": "wav"}}` |

No necesitas mapear estas partes al formato de cada proveedor: los *serializers*
automáticos de cada provider (`OpenAICompatibleProvider`, `AnthropicProvider`,
`GeminiProvider`, `AzureOpenAIProvider`, `LiteLLMProvider`) convierten el
`content` multimodal a la representación nativa (bloques `image` de Anthropic,
`inline_data` de Gemini, etc.) de forma transparente.

Método de ayuda:

- `ChatMessage.text() -> str` — devuelve el texto plano concatenando las
  partes de tipo `"text"` e **ignorando** imágenes/audio. Útil para CLI,
  gateway y resúmenes sin romper la API pública.

```python
from ciel.runtime import ChatMessage

# Texto plano (sigue funcionando igual)
msg = ChatMessage(role="user", content="hola")
assert msg.text() == "hola"

# Multimodal: pregunta sobre una imagen (data-URL)
img = ChatMessage(
    role="user",
    content=[
        {"type": "text", "text": "¿Qué hay en esta imagen?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}},
    ],
)
# .text() solo entrega el texto legible
assert img.text() == "¿Qué hay en esta imagen?"
```

## Proveedores disponibles

| Clase                  | Módulo                      | Notas                                                        |
|------------------------|-----------------------------|--------------------------------------------------------------|
| `OpenAICompatibleProvider` | `ciel.providers`        | OpenAI y cualquier endpoint compatible (`/v1`).              |
| `AnthropicProvider`    | `ciel.providers`            | Claude. Mapea `image_url` a bloques `image` base64.         |
| `GeminiProvider`       | `ciel.providers.gemini`     | Gemini. Mapea `image_url` a `inline_data`.                  |
| `AzureOpenAIProvider`  | `ciel.providers.azure`      | Azure OpenAI (deployment + `api-version`).                  |
| `LiteLLMProvider`      | `ciel.providers.litellm`    | Meta-provider de 100+ modelos. **Requiere el extra `litellm`.** |

### `LiteLLMProvider` (extra `litellm`)

Expone 100+ modelos tras un único contrato `ChatProvider` delegando en la
librería `litellm`. Es **offline-safe**: `litellm` solo se importa al
construir/usar el provider, así el import por defecto del framework no arrastra
la dependencia pesada.

```bash
pip install "mana-ciel[litellm]"
```

```python
from ciel.providers.litellm import LiteLLMProvider

provider = LiteLLMProvider(
    model="gpt-4o-mini",
    api_key="sk-...",
    # models=[...]  -> opcional: Router LiteLLM para fallback/balanceo
)
```

Si se omite el extra, la construcción lanza `ProviderError` claro:
`The 'litellm' extra is required for LiteLLMProvider. Install it with:
pip install "mana-ciel[litellm]"`.

### `AzureOpenAIProvider`

Azure OpenAI es compatible con OpenAI pero requiere el parámetro de consulta
`api-version` y direcciona un **deployment** (no el id de modelo crudo). Esta
subclase de `OpenAICompatibleProvider` inyecta la versión en cada request y
trata el campo `model`/`deployment` como el nombre del deployment.

```python
from ciel.providers.azure import AzureOpenAIProvider

provider = AzureOpenAIProvider(
    base_url="https://<resource>.openai.azure.com",
    api_key="...",            # AZURE_OPENAI_API_KEY
    deployment="gpt-4o",      # nombre del deployment en Azure
    api_version="2024-06-01",
)
```

### Auto-provider por prefijo de modelo

`ciel.providers.auto.auto_provider(model)` infiere el provider a partir del
prefijo del id de modelo (lee la API key del entorno):

| Prefijo        | Provider                       | Base URL por defecto        |
|----------------|--------------------------------|-----------------------------|
| `gpt-`, `o1`, `o3` | OpenAI-compatible          | `https://api.openai.com/v1` |
| `claude-`      | Anthropic                     | `https://api.anthropic.com/v1` |
| `gemini-`, `models/` | Gemini                   | —                           |
| `azure/`       | `AzureOpenAIProvider`         | `AZURE_OPENAI_ENDPOINT`     |
| `ollama/`      | OpenAI-compatible (local)     | `http://localhost:11434/v1` |
| `vllm/`        | OpenAI-compatible (self-host) | `http://localhost:8000/v1` (o `VLLM_BASE_URL`) |

`ciel.Agent(model="gpt-4o-mini")` usa esto internamente; un `provider=`
explícito siempre gana sobre la inferencia.

::: ciel.providers
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.providers.azure
    options:
      show_root_heading: false
      members: true

::: ciel.providers.litellm
    options:
      show_root_heading: false
      members: true

::: ciel.providers.gemini
    options:
      show_root_heading: false
      members: true
