# Fase 9 — Extensibilidad: plugin system, providers reales, tools de fábrica, DX

Fecha: 2026-07-14. Objetivo: convertir Ciel de "código con columna vertebral" en
un **framework extensible** donde terceros añaden providers/tools/agents sin tocar
el core, y con documentación de DX externa digna.

## 1. Principio rector
NO reinventar. Ya existen contratos sólidos:
- `ciel.providers`: `ChatProvider` (ABC), `ProviderRegistry`, `ProviderFactory`,
  `OpenAICompatibleProvider`, `AnthropicProvider` (reales, offline-safe).
- `ciel.runtime.tools`: `ToolSpec`, `Tool`, `ToolRegistry`, `ToolsetSchema`,
  `DefaultToolDispatcher`, `AgentRuntime`.
La Fase 9 añade una CAPA DE DESCUBRIMIENTO (entry_points) sobre esto, sin romperlo.

## 2. Plugin system (`ciel.plugins`)
Nuevo paquete `src/ciel/plugins/`:
- `PluginRegistry`: registra/descubre providers, tools, agents por nombre.
- `discover_plugins(group)` usando `importlib.metadata.entry_points` (stdlib,
  offline-safe, sin deps extra). Grupos: `ciel.providers`, `ciel.tools`, `ciel.agents`.
- `load_builtin_plugins()`: registra los providers/tools que vienen con el core
  (OpenAICompatible, Anthropic, Gemini, tools de fábrica) para que estén disponibles
  sin entry_points (modo integrado).
- API pública: `ciel.plugins.register(...)`, `ciel.plugins.get_provider(name)`,
  `ciel.plugins.list_tools()`, `ciel.plugins.get_toolset(name)`.

Contratos de plugin (lo que debe exponer un tercero):
- Provider plugin: subclase `ciel.providers.ChatProvider` + función `register(registry)`.
- Tool plugin: `ToolSpec` + callable, registrado vía `ToolRegistry`.
- Agent plugin: clase agente que expone `run(request)`.

## 3. Providers reales empaquetados como builtins
- `OpenAICompatibleProvider` y `AnthropicProvider` YA existen → se registran en
  `load_builtin_plugins()`.
- Añadir `GeminiProvider` (Google AI Studio / Vertex) como builtin, offline-safe
  (solo hace HTTP si se le da api_key; en tests se usa mock).
- `ProviderFactory` se extiende para consultar el `PluginRegistry` (no solo URL).

## 4. Tools de fábrica (`ciel.runtime.tools.builtins`)
Set mínimo útil y OFFLINE-SAFE (los que tocan red se guardan tras try/except y
se documentan como "requieren red"):
- `echo_tool` (siempre offline) — para smoke y ejemplos.
- `http_get_tool` (requiere red; en tests usa mock client inyectado).
- `file_read_tool` / `file_write_tool` (local, sandboxeado por `ciel.sandbox`).
- `shell_tool` (requiere `ciel.sandbox`, desactivado por defecto por seguridad).
- `datetime_tool` (offline).
Se registran en un `ToolsetSchema` "builtins" y en `load_builtin_plugins()`.

## 5. `ciel init` (scaffold)
- `ciel.cli.main` gana subcomando `init [PATH]` que genera:
  - `pyproject.toml` con extra `ciel` + entry_points `ciel.plugins` de ejemplo.
  - `my_agent.py` con un agente mínimo + tool dummy (reusa patrón quickstart).
  - `ciel.yaml` mínimo.
- Offline-safe (sin red). Idempotente sobre directorio existente (no pisa archivos).

## 6. Verificación
- Tests formales nuevos `tests/test_fase9_plugins_test.py` + `tests/test_fase9_tools_test.py`:
  - registro/descubrimiento de provider por nombre; GeminiProvider offline (mock).
  - registro de tool propia; dispatch vía DefaultToolDispatcher; toolset builtins.
  - `ciel init` genera archivos y el agente generado corre offline (smoke).
- Regresión completa `uv run pytest tests/` verde (216 + N).
- Subagente DX paralelo crea `docs/guide/*` + `examples/quickstart_agent.py` (offline).

## 7. Criterio de avance
- Tercero puede `pip install mi-plugin-ciel` y su provider/tool aparece en el registry
  sin importar código manual. ✅ (entry_points discovery)
- `ciel init` genera proyecto que corre offline. ✅
- Docs externas en `docs/guide/` con quickstart ejecutable. ✅ (subagente)
- Regresión verde. ✅
