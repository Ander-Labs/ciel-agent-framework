# Tools (herramientas)

Las tools dan al agente capacidades más allá del texto: llamar APIs, leer
archivos, ejecutar código, etc. Con la API de alto nivel defines una tool como
una **función Python normal** decorada con `@ciel.tool`.

## Definir una tool con `@ciel.tool`

```python
import ciel

@ciel.tool
def buscar_clima(ciudad: str) -> dict:
    "Devuelve el clima de una ciudad."
    return {"ciudad": ciudad, "temp_c": 21}
```

Ciel infiere automáticamente:

- **El esquema JSON de parámetros** desde los *type hints* (con Pydantic v2).
- **La descripción** desde el docstring de la función.
- **El nombre** desde el nombre de la función (o el que le pases explícito).

La función decorada sigue siendo llamable como Python normal
(`buscar_clima("Lima")`), y expone `.as_tool` (el objeto `Tool` interno),
`.name` y `.description`.

### Nombre y descripción explícitos

```python
@ciel.tool(name="clima", description="Clima actual por ciudad.")
def buscar_clima(ciudad: str) -> dict:
    return {"ciudad": ciudad, "temp_c": 21}
```

### Type hints complejos

Se soportan `List`, `Dict`, `Optional`, `Union`, etc. (todo lo que Pydantic v2
sepa serializar a JSON Schema):

```python
from typing import List, Optional

@ciel.tool
def filtrar(nombres: List[str], limite: Optional[int] = None) -> list:
    "Filtra una lista de nombres."
    return nombres[: (limite or len(nombres))]
```

## Inyección de dependencias con `Context`

Declara un parámetro anotado con `ciel.Context` y Ciel lo **inyecta en tiempo de
ejecución** y lo **excluye del esquema** (el modelo nunca lo ve). Útil para
multitenancy y trazabilidad:

```python
@ciel.tool
def quien_soy(ctx: ciel.Context) -> str:
    "Devuelve el tenant actual."
    return f"tenant={ctx.tenant_id}"
```

`Context` expone `tenant_id`, `session_id`, `user`, `tool_call_id` y `metadata`.
El `tenant_id` que pases a `Agent.run(..., tenant_id="acme")` llega aquí.

## Tools `async`

`@ciel.tool` también acepta funciones `async`; el runtime las *awaitea*:

```python
@ciel.tool
async def fetch(url: str) -> str:
    "Descarga una URL."
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.get(url)
        return r.text
```

## Usar las tools en un agente

```python
agent = ciel.Agent(provider=mi_provider, tools=[buscar_clima, quien_soy])
resp = agent.run("¿Qué clima hace en Lima?", tenant_id="acme")
for r in resp.tool_results:
    print(r.name, r.output)
```

---

## API de bajo nivel (avanzado)

La fachada anterior se construye sobre contratos públicos que puedes usar
directamente si necesitas control fino (registro por tenant, dispatch manual,
toolsets activables):

- `ToolSpec`: nombre, descripción, esquema de parámetros.
- `Tool`: `ToolSpec` + `callable_`.
- `ToolRegistry` / `ToolsetSchema`: agrupan tools en *toolsets*.
- `DefaultToolDispatcher` + `ToolProvider`: ejecutan `tool_calls` contra el registry.

```python
from ciel.runtime import DefaultToolDispatcher, ToolProvider
from ciel.runtime.tools import Tool, ToolRegistry, ToolSpec, ToolResult

def sumar(arguments, *, tool_call_id="", tenant_id=None) -> ToolResult:
    a, b = arguments.get("a", 0), arguments.get("b", 0)
    return ToolResult(id=tool_call_id, name="sumar", output={"result": a + b})

registry = ToolRegistry(default_toolset="default")
registry.register_tool("default", Tool(
    spec=ToolSpec(name="sumar", description="Suma dos números",
                  parameters={"type": "object",
                              "properties": {"a": {"type": "integer"},
                                             "b": {"type": "integer"}}}),
    callable_=sumar,
))
dispatcher = DefaultToolDispatcher(
    provider=ToolProvider(registry=registry, require_tenant_on_execution=False),
    default_toolset="default",
)
result = await dispatcher.dispatch(name="sumar", arguments={"a": 2, "b": 3},
                                   tool_call_id="1")
print(result.output)   # {'result': 5}
```

Ejemplo completo ejecutable: `examples/lowlevel_agent.py`.

## Tools de fábrica

`ciel.runtime.tools_builtins` registra el toolset `builtins` con `echo`,
`datetime`, `http_get`, `file_read` y `shell` (sandboxeadas):

```python
from ciel.runtime.tools_builtins import register_builtin_tools
register_builtin_tools(registry)   # añade el toolset "builtins"
```
