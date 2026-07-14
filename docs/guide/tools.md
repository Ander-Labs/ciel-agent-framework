# Tools (herramientas)

Las tools dan al agente capacidades más allá del texto: llamar APIs, leer
archivos, ejecutar código, etc.

## Definir una tool

```python
from ciel.runtime.tools import Tool, ToolSpec, ToolResult

def buscar_clima(arguments, *, tool_call_id="", tenant_id=None) -> ToolResult:
    ciudad = arguments.get("ciudad", "desconocida")
    return ToolResult(id=tool_call_id, name="buscar_clima",
                      output={"ciudad": ciudad, "temp_c": 21})

spec = ToolSpec(
    name="buscar_clima",
    description="Devuelve el clima de una ciudad",
    parameters={"ciudad": {"type": "string"}},
)
tool = Tool(spec=spec, callable_=buscar_clima)
```

El `callable_` debe aceptar `arguments` y devolver un `ToolResult`. Los
parámetros `tool_call_id` y `tenant_id` son inyectados por el dispatcher.

## Registrar en un toolset

```python
from ciel.runtime.tools import ToolRegistry

registry = ToolRegistry(default_toolset="default")
registry.register_tool("default", tool)
```

## Ejecutar vía dispatcher

```python
from ciel.runtime import DefaultToolDispatcher, ToolProvider

dispatcher = DefaultToolDispatcher(
    provider=ToolProvider(registry=registry, require_tenant_on_execution=False),
    default_toolset="default",
)

result = await dispatcher.dispatch(name="buscar_clima",
                                   arguments={"ciudad": "Lima"},
                                   tool_call_id="1")
print(result.output)   # {'ciudad': 'Lima', 'temp_c': 21}
```

El `DefaultAgentRuntime` ya usa el dispatcher internamente: cuando el provider
devuelve `tool_calls`, el runtime los despacha y reinyecta los resultados.

## Tools de fábrica

`ciel.runtime.tools_builtins` registra el toolset `builtins` con:

- `echo` — repite texto (offline).
- `datetime` — fecha/hora actual (offline).
- `http_get` — GET HTTP (client inyectable para tests).
- `file_read` — lectura de archivos (sandboxeada).
- `shell` — ejecución de comandos (sandboxeada vía `ciel.sandbox`).

```python
from ciel.runtime.tools_builtins import register_builtin_tools
register_builtin_tools(registry)   # añade el toolset "builtins"
```
