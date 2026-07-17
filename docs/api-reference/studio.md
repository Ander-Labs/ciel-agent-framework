# Referencia API — Ciel Studio (`ciel.studio`)

Módulo: `ciel.studio`. Ofrece un dashboard de observabilidad en memoria,
offline-safe y multitenant.

## `StudioStore`

Store en memoria de sesiones y loops por tenant.

```python
from ciel.studio import StudioStore

store = StudioStore()
store.record_session(tenant_id="acme", agent="a1",
                    prompt="hola", text="hi", tool_calls=2, turns=3)
store.record_loop(tenant_id="acme", agent="a1", status="running")

sessions = store.list_sessions(tenant_id="acme")   # filtro opcional
loops    = store.list_loops(tenant_id="acme")
snapshot  = store.snapshot(tenant_id="acme")
# snapshot = {"sessions": [...], "loops": [...], "counts": {...}}
```

### Métodos

| Método | Descripción |
|--------|-------------|
| `record_session(*, tenant_id, agent, prompt="", text="", finish_reason="stop", tool_calls=0, turns=0, session_id=None)` | registra/crea una `SessionRecord` |
| `update_session(session_id, **changes)` | actualiza campos; devuelve `None` si no existe |
| `get_session(session_id)` | `SessionRecord` o `None` |
| `list_sessions(*, tenant_id=None)` | lista ordenada por `updated_at` desc |
| `record_loop(*, tenant_id, agent, loop_id=None, status="running")` | registra un `LoopRecord` |
| `update_loop(loop_id, **changes)` | actualiza campos; `None` si no existe |
| `list_loops(*, tenant_id=None)` | lista ordenada por `updated_at` desc |
| `snapshot(*, tenant_id=None)` | dict con `sessions`, `loops`, `counts` |

## `get_studio_store()` / `reset_studio_store()`

```python
from ciel.studio import get_studio_store, reset_studio_store

store = get_studio_store()      # singleton por proceso
reset_studio_store()            # reinia (útil en tests)
```

## `install_studio_support(agent, store=None)`

Envuelve `agent.run` / `agent.arun` para registrar cada sesión. **Fachada:**
no cambia la firma ni el retorno. Devuelve el `StudioStore` usado.

```python
from ciel.studio import install_studio_support

store = install_studio_support(agent)
agent.run("ping", tenant_id="acme")
assert len(store.list_sessions(tenant_id="acme")) == 1
```

## `create_studio_router(store=None, path="/v1/studio")`

Router FastAPI del dashboard. Requiere el extra `server` (FastAPI).

| Ruta | Método | Descripción |
|------|--------|-------------|
| `{path}` | `GET` | snapshot completo (`?tenant=` opcional) |
| `{path}/sessions` | `GET` | lista de sesiones (`?tenant=`) |
| `{path}/loops` | `GET` | lista de loops (`?tenant=`) |
| `{path}/health` | `GET` | `{"status": "ok", "channel": "studio"}` |

`ciel serve` lo monta automáticamente; `ciel studio show` lo imprime en
consola. Ver también la [guía de Ciel Studio](../guide/studio.md).
