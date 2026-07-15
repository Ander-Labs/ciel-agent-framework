# `ciel.providers` — Proveedores de modelos

Contratos y proveedores de modelos agnósticos al proveedor. Define los DTOs de
configuración (`ProviderConfig`, `ModelInfo`), el contrato `ChatProvider` y un
registro/fábrica (`ProviderRegistry`, `ProviderFactory`), junto con
implementaciones `OpenAICompatibleProvider` y `AnthropicProvider`.

!!! note
    Los DTOs de solicitud/respuesta de chat (`ChatRequest`, `ChatResponse`,
    `ChatMessage`, `ChatChoice`) se definen en `ciel.runtime` y se reutilizan
    aquí.

::: ciel.providers
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.providers.gemini
    options:
      show_root_heading: false
      members: true
