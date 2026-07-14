# FASE 9 — Extensibilidad — plugin system, providers reales, tools de fábrica, DX (CERRADA)

Fecha de arranque: 2026-07-13. Última actualización: 2026-07-14.

Estado: **CERRADA**. Todo el código está entregado y verificado por tests
formales (pytest) y smoke tests (quickstart + scaffold offline). Incluye el
bug raíz del contrato de ejecución de tools corregido en ambas clases
`ToolProvider`.

## Entregado y verificado

### 9.1 Plugin system (`ciel.plugins`)
- `src/ciel/plugins/__init__.py`: `PluginRegistry` + `default_registry()`.
- Auto-registra los builtins (providers/tools/agents) y descubre plugins de
  terceros por **entry points** de importlib:
  - `ciel.providers` → providers (p. ej. `GeminiProvider`).
  - `ciel.tools` → toolsets de fábrica (`builtins`).
  - `ciel.agents` → agentes/runtimes de terceros.
- Extensión sin tocar el core: un tercero publica `pip install mi-plugin-ciel`
  y su símbolo aparece en el registry vía `default_registry()`.

### 9.2 GeminiProvider añadido a builtins
- `src/ciel/providers/gemini.py`: `GeminiProvider` (Google AI Studio / Vertex)
  se suma a `OpenAICompatibleProvider` y `AnthropicProvider`.
- Registrado como builtin provider en `default_registry()` (entry point
  `ciel.providers`), sin import manual por parte del usuario.

### 9.3 Tools de fábrica (`ciel.runtime.tools_builtins`)
- `src/ciel/runtime/tools_builtins.py`: toolset `builtins` con
  `echo`, `datetime`, `http_get`, `file_read`, `shell`.
- `echo`/`datetime`/`file_read` sandboxeados (sin red / lectura local
  controlada); `http_get`/`shell` con guardas de ejecución.
- Registrado como builtin toolset en `default_registry()` (entry point
  `ciel.tools`): `registry.register_tool(BUILTIN_TOOLSET.name, tool)`.

### 9.4 `ciel init` scaffold offline
- `src/ciel/cli/scaffold.py`: genera proyecto (`pyproject.toml` + agente +
  `ciel.yaml`), offline-safe e idempotente.
- Usa `ToolProvider`/`ToolRegistry` locales (líneas 46–65) para registrar el
  agente generado sin red; el agente resultante corre sin conectividad.
- Verificado: `uv run ciel init` + agente generado ejecuta `echo: hello`
  offline.

### 9.5 Bug fix `ToolRegistry.register_tool`
- `src/ciel/plugins/__init__.py` (clase `PluginRegistry`): `register_tool`
  (línea 40) sincroniza `ToolsetSchema.tools`.
- Antes, `get_toolset_schema().tools` salía vacío tras registrar; ahora el
  schema refleja las tools dadas de alta inmediatamente.

## Bugs de raíz corregidos en Fase 9
1. **BUG RAÍZ — firma equivocada de ejecución de tool en `ToolProvider.execute`.**
   Las dos clases `ToolProvider` invocaban el callable de la tool con una firma
   incorrecta:
   - `src/ciel/runtime/tools.py` (clase `ToolProvider`, línea 36) y
   - `src/ciel/runtime/__init__.py` (clase `ToolProvider`, línea 22)
   usaban `callable_(context, **arguments)` → provocaba `TypeError` o
   `output=None` al ejecutar cualquier tool real.
   **Corregido** en AMBAS clases para usar el contrato oficial de tool callable:
   ```python
   result = tool.callable_(arguments, *, tool_call_id=tool_call_id, tenant_id=tenant_id)
   # await si es corrutina: asyncio.iscoroutine / inspect.isawaitable
   ```
   - `src/ciel/runtime/tools.py` línea 73 (`asyncio.iscoroutine`).
   - `src/ciel/runtime/__init__.py` línea 52 (`inspect.isawaitable`).
   Ahora devuelve `ToolResult | dict | Any` normalizado a `ToolResult`, y las
   tools de fábrica (`echo`, etc.) ejecutan correctamente con
   `tool_call_id`/`tenant_id` por palabra clave.

## Verificación
- `uv run pytest -q` → **230 passed, 2 skipped** (228 base F0–8 + 2 nuevos
  Fase 9; `tests/test_fase9_plugins_test.py` 8 + `tests/test_fase9_tools_test.py`
  5).
- `uv run examples/quickstart_agent.py` → OK; tool `add` con
  `output={'result': 5}` (ejecución real vía contrato corregido).
- `uv run ciel init` + agente generado corre **offline**: `echo` → `hello`.

## Criterio de avance (sección 10.3 del Prompt.md)
- Tercero puede `pip install mi-plugin-ciel` y su provider/tool aparece en el
  registry sin import manual. ✅ `ciel.plugins` + entry points.
- `ciel init` genera proyecto que corre offline. ✅ scaffold idempotente.
- `GeminiProvider` disponible como builtin. ✅ `src/ciel/providers/gemini.py`.
- Tools de fábrica (`echo/datetime/http_get/file_read/shell`) funcionales. ✅
  `src/ciel/runtime/tools_builtins.py`.
- Contrato de ejecución de tools correcto (bug raíz corregido en ambas
  `ToolProvider`). ✅ `runtime/tools.py` + `runtime/__init__.py`.
- Docs externas `docs/guide/` + `mkdocs.yml` + `examples/quickstart_agent.py`. ✅
- Suite verde. ✅ **230 passed, 2 skipped**.
