# Guía de migración: v0.2.0 → v0.3.0

> Actualiza `mana-ciel` desde la versión v0.2.0 a la v0.3.0 (Fase 9:
> extensibilidad). Esta guía es para **usuarios** del framework.

```bash
pip install --upgrade mana-ciel==0.3.0
```

## ⚠️ Cambio de contrato de tool callable (breaking)

La firma oficial de una tool cambió. Ahora es:

```python
def my_tool(
    arguments: dict,
    *,
    tool_call_id: str,
    tenant_id: str | None,
) -> ToolResult | dict | Any:
    ...
```

Reglas:

- `arguments` es un `dict` **posicional** (no `**kwargs`).
- `tool_call_id` y `tenant_id` son **keyword-only**.
- El valor de retorno puede ser un `ToolResult`, un `dict` (serializable como
  `ToolResult`) o cualquier valor crudo; las excepciones se capturan en
  `ToolResult.error` y las corrutinas se `await` automáticamente.

### Tools con la firma vieja (deben migrar)

Si tu tool usa la firma antigua `callable_(context, **arguments)`:

```python
# ❌ viejo — ya no funciona
def my_tool(context, **arguments):
    return {"result": arguments["x"]}
```

Migra a:

```python
# ✅ nuevo — firma oficial
def my_tool(arguments, *, tool_call_id, tenant_id):
    return {"result": arguments["x"]}
```

- El `context` antiguo desaparece; usa `tenant_id` (y pasa lo que necesites por
  `arguments`).
- Reemplaza `**arguments` por un `dict` posicional.
- Añade los parámetros keyword-only `tool_call_id` y `tenant_id` (puedes
  ignorarlos si no los necesitas, pero deben estar en la firma).

## Novedades v0.3.0

- **Plugin system** (`ciel.plugins`): `PluginRegistry` + `default_registry()`
  auto-registran builtins y descubren plugins de terceros vía entry points
  (`ciel.providers`, `ciel.tools`, `ciel.agents`). Extiende el framework sin
  tocar el core: `pip install mi-plugin-ciel`.
- **GeminiProvider** (`ciel.providers.gemini`): nuevo provider empaquetado,
  registrado como builtin junto a `OpenAICompatibleProvider` y `AnthropicProvider`.
- **Tools de fábrica** (`ciel.runtime.tools_builtins`): toolset `builtins`
  (`echo`, `datetime`, `http_get`, `file_read`, `shell` sandboxeado).
- **`ciel init`**: scaffold de proyecto (pyproject + agent + `ciel.yaml`),
  offline-safe e idempotente.

## Pasos recomendados

1. Actualiza la firma de tus tools a la oficial (arriba).
2. Si publicas tools/providers propios, regístralos vía entry points
   `ciel.tools` / `ciel.providers` o usa `default_registry().register_*`.
3. Prueba tu proyecto con `ciel init` + el agente generado como base offline.
4. `pip install --upgrade mana-ciel==0.3.0`.

## Enlaces

- Roadmap público (futuras versiones): [roadmap.md](roadmap.md)
- Releases de GitHub: <https://github.com/Ander-Labs/ciel-agent-framework/releases>
