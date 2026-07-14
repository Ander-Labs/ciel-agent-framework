# Tutorial: escribe tu primer plugin de Ciel

En este tutorial creas un plugin de terceros que aporta un **provider** y un
**toolset** a Ciel, sin tocar el core. Tras instalarlo, aparecen automáticamente
en `default_registry()`.

Todo el tutorial corre **offline** (no necesitas API keys).

## Qué vas a construir

- Un package `mi_plugin_ciel` con:
  - Un provider mock `saludo` (hereda `ChatProvider`).
  - Un toolset `saludo` con la tool `decir_hola`.
- Declaración vía *entry points* (`ciel.providers`, `ciel.tools`).
- Verificación: `default_registry().list_providers()` y `.list_toolsets()`
  muestran tu plugin tras instalarlo.

## 1. Estructura

```
mi_plugin_ciel/
├── pyproject.toml
└── mi_plugin_ciel/
    ├── __init__.py
    └── plugin.py
```

## 2. El código (`mi_plugin_ciel/plugin.py`)

```python
from __future__ import annotations

from ciel.providers import ChatProvider
from ciel.runtime.tools import Tool, ToolRegistry, ToolSpec, ToolResult
from ciel.plugins import plugin_register


# --- Provider mock ---------------------------------------------------------
class SaludoProvider(ChatProvider):
    provider_name = "saludo"

    async def complete(self, request):  # pragma: no cover - demo
        from ciel.providers import ChatChoice, ChatMessage, ChatResponse
        text = request.messages[-1].content if request.messages else ""
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=f"(saludo) {text}"),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request):  # pragma: no cover - demo
        return [await self.complete(request)]

    async def models(self):  # pragma: no cover - demo
        return []


# --- Tool con la FIRMA OFICIAL --------------------------------------------
def decir_hola(arguments, *, tool_call_id="", tenant_id=None) -> ToolResult:
    nombre = arguments.get("nombre", "mundo")
    return ToolResult(id=tool_call_id, name="decir_hola",
                      output={"saludo": f"Hola, {nombre}!"})


# --- Hooks de registro (entry points) ------------------------------------
@plugin_register("ciel.providers")
def register_provider(registry) -> None:
    registry.register_provider("saludo", SaludoProvider())


@plugin_register("ciel.tools")
def register_tools(registry) -> None:
    reg: ToolRegistry = registry.tools
    reg.register_tool("saludo", Tool(
        spec=ToolSpec(name="decir_hola", description="Saluda a quien indiques",
                      parameters={"nombre": {"type": "string"}}),
        callable_=decir_hola,
    ))
```

> **Firma oficial de tool**: `callable_(arguments: dict, *, tool_call_id, tenant_id)`
> → `ToolResult | dict | Any`. Si devuelves un valor crudo (dict) se envuelve en
> `ToolResult`; si es corrutina, se hace `await`. Ver [Tools](tools.md).

`mi_plugin_ciel/__init__.py` puede quedar vacío o re-exportar `plugin.py`.

## 3. El `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mi-plugin-ciel"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["mana-ciel>=0.3.0"]

[project.entry-points."ciel.providers"]
saludo = "mi_plugin_ciel.plugin:register_provider"

[project.entry-points."ciel.tools"]
saludo = "mi_plugin_ciel.plugin:register_tools"
```

Los grupos de entry point son exactamente: `ciel.providers`, `ciel.tools`,
`ciel.agents`. Cada entrada apunta a una función marcada con `@plugin_register`
(o directamente a un objeto provider/tool.

## 4. Instalar en modo editable

Desde la carpeta `mi_plugin_ciel/`:

```bash
uv pip install -e .
# o: pip install -e .
```

## 5. Verificar que Ciel lo descubre

```python
from ciel.plugins import default_registry

reg = default_registry()
print("providers:", reg.list_providers())   # incluye "saludo" + openai/anthropic/gemini
print("toolsets:", reg.list_toolsets())     # incluye "saludo" + "builtins"
```

Deberías ver `saludo` en ambas listas. ¡Listo: tu plugin se auto-descubrió!

## 6. Usarlo en un agente

```python
from ciel.plugins import default_registry
from ciel.runtime import DefaultAgentRuntime, DefaultToolDispatcher, ToolProvider
from ciel.providers import ChatRequest, ChatMessage

reg = default_registry()
# El provider "saludo" y el toolset "saludo" ya están registrados.
dispatcher = DefaultToolDispatcher(
    provider=ToolProvider(registry=reg.tools, require_tenant_on_execution=False),
    default_toolset="saludo",
)
runtime = DefaultAgentRuntime(provider=reg.get_provider("saludo"), dispatcher=dispatcher)

# (Omite la ejecución real: SaludoProvider es un mock mínimo de demo.)
```

## Solución de problemas

- **No aparece el plugin**: confirmá que instalaste con `uv pip install -e .`
  (no solo `python setup.py`) para que los entry points se registren, y que el
  grupo sea `ciel.providers` / `ciel.tools` / `ciel.agents` literal.
- **Importa antes de instalar**: `default_registry()` cachea en un singleton;
  si lo llamaste antes de instalar el plugin en el mismo proceso, reiniciá el
  intérprete.
- **La tool no corre**: revisá que el callable use la firma oficial
  `callable_(arguments, *, tool_call_id, tenant_id)`. La firma vieja
  `callable_(context, **arguments)` ya no funciona (migración v0.3.0).

## Siguiente paso

Publicá tu plugin en PyPI (`uv build` + `uv publish`) y cualquiera puede hacer
`pip install mi-plugin-ciel` para extender Ciel sin tocar el core.
