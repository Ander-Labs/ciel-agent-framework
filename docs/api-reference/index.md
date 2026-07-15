# Referencia de API

Esta sección documenta automáticamente los módulos públicos del paquete
`ciel` (PyPI `mana-ciel`) a partir de sus docstrings mediante
[mkdocstrings](https://mkdocstrings.github.io/) (handler de Python).

La generación usa `google` como estilo de docstring y muestra el código fuente
(`show_source: true`). Cada página enlazada a continuación documenta un
paquete público de `ciel`:

| Módulo | Descripción |
|--------|-------------|
| [`ciel.cli`](cli.md) | Aplicación y comandos de línea de comandos (`ciel`). |
| [`ciel.observability`](observability.md) | Auditoría multi-tenant y trazas de herramientas. |
| [`ciel.adapters`](adapters.md) | Adapters de mensajería agnósticos al canal (Teams, Discord, Web UI). |
| [`ciel.gateway`](gateway.md) | Superficie de gateway: FastAPI, MCP y routers de mensajería. |
| [`ciel.providers`](providers.md) | Contratos y proveedores de modelos (OpenAI-compatible, Anthropic). |
| [`ciel.runtime`](runtime.md) | Runtime de agentes, tool loop, DTOs de chat y despacho de tools. |
| [`ciel.security`](security.md) | Políticas de aprobación y redacción de secretos/PII. |
| [`ciel.orchestration`](orchestration.md) | Orquestación: grafos de estado, flows, group chat, agentes autónomos. |

!!! tip "Cómo leer esta referencia"
    Cada símbolo público (`__all__`) de los paquetes se genera desde el código
    fuente. Las firmas incluyen anotaciones de tipo y un enlace al código
    fuente cuando está disponible.
