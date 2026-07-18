# Contenido multimodal (imágenes)

Envía una imagen a un agente multimodal usando partes de contenido en
`ChatMessage.content`. No hace falta mapear al formato del proveedor: Ciel
convierte `image_url` (data-URL) a bloques nativos de OpenAI/Anthropic/Gemini.

```python
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


@ciel.tool
def describe_image(caption: str) -> str:
    "Devuelve la descripción recibida para la imagen."
    return f"Imagen descrita: {caption}"


# Provider de ejemplo que "ve" el texto de la imagen vía tool call.
class DummyVisionProvider(ChatProvider):
    provider_name = "dummy_vision"

    async def complete(self, request):
        # El runtime expone content multimodal; .text() entrega solo el texto.
        user_text = request.messages[-1].text()
        tc = [{"id": "c1", "name": "describe_image",
               "arguments": {"caption": user_text}}]
        msg = ChatMessage(role="assistant", content="", tool_calls=tc)
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="tool_calls"),
            metadata={"tool_calls": tc},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy_vision", provider="dummy_vision"),)


# data-URL mínima (sustituye por tu PNG/JPG en base64 real).
IMAGE_DATA_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMCAQDJ/3pUAAAAAElFTkSuQmCC"

# Puedes pasar el prompt multimodal directo a agent.run(...):
prompt = [
    {"type": "text", "text": "¿Qué hay en esta imagen?"},
    {"type": "image_url", "image_url": {"url": IMAGE_DATA_URL}},
]

agent = ciel.Agent(provider=DummyVisionProvider(), tools=[describe_image], toolset="demo")
resp = agent.run(prompt, tenant_id="acme")

print(resp.tool_results[0].output)
```

Qué esperar:

```text
Imagen descrita: ¿Qué hay en esta imagen?
```

Notas:

- `agent.run(prompt)` acepta `str | list[dict]` (el `prompt` se pasa tal cual
  a `ChatMessage.content`).
- `ChatMessage.text()` concatena solo las partes `"text"` e ignora la imagen,
  por eso el tool recibe la pregunta legible.
- Con un provider real (OpenAI `gpt-4o`, Claude, Gemini, Azure, Ollama, vLLM o
  LiteLLM), la imagen se reenvía al modelo; solo cambia el `provider=` /
  `model=`. Ver `docs/api-reference/providers.md`.
