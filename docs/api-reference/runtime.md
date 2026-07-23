# `ciel.runtime` — Runtime de agentes y tools

Núcleo del runtime: DTOs de chat (`ChatMessage`, `ChatChoice`, `ChatRequest`,
`ChatResponse`), contratos de provider/modelo (`ChatProvider`, `ModelProvider`),
tool loop y despacho de herramientas (`ToolProvider`, `DefaultToolDispatcher`),
resultados de ejecución (`ToolLoopResult`, `AgentRuntimeResult`, `AgentContext`)
y el runtime concreto con trazas (`DefaultAgentRuntime`, `AgentRuntime`).

## `ChatMessage.content` (multimodal)

`ChatMessage.content` es `str | list[dict[str, Any]]`:

- `str` — texto plano (compatibilidad total con versiones previas).
- `list[dict]` — **partes multimodales** (`text`, `image_url`, `input_audio`).
  Los providers convierten estas partes a su formato nativo automáticamente.

`ChatMessage.text() -> str` concatena las partes de tipo `"text"` e ignora
imágenes/audio (ver `docs/api-reference/providers.md` para los serializers por
proveedor y ejemplos de partes).

::: ciel.runtime
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.runtime.tools
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.tools_builtins
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.memory
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.prompt_versioning
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.reflection_agent_integration
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.cognitive_state
    options:
      show_root_heading: false
      members: true
