# Referencia API — Ciel Studio: Trace (`ciel.studio_trace`)

Módulo: `ciel.studio_trace`. Trazabilidad offline de checkpoints de grafos
para **graph view + replay / time-travel** (Fase 13 / F20).

## `GraphTraceStore`

Store en memoria de checkpoints de grafos por tenant.

```python
from ciel.studio_trace import GraphTraceStore, attach_trace
from ciel.orchestration.graph import GraphCheckpointStore
from ciel.runtime.memory import MemoryStore

backend = MemoryStore()
checkpointer = GraphCheckpointStore(backend)
trace = attach_trace(checkpointer)  # cada save() también se registra

# ... ejecutas el grafo (guarda checkpoints) ...

runs = trace.list_runs(tenant_id="acme")
run = trace.get_run(run_id, tenant_id="acme")  # dict con steps[] ordenados
states = trace.replay(run_id)                   # lista de estados step a step
```

### Métodos

| Método | Descripción |
|--------|-------------|
| `record_checkpoint(payload)` | registra un `TraceStep` desde el payload de `GraphCheckpointStore.save` |
| `list_runs(*, tenant_id=None)` | runs únicos ordenados por último step |
| `get_run(run_id, *, tenant_id=None)` | `dict` con `run_id`, `tenant_id`, `steps[]` |
| `steps_of(run_id)` | pasos de un run |
| `replay(run_id)` | lista de `state.snapshot()` por paso (time-travel) |
| `snapshot(*, tenant_id=None)` | `{runs, steps, counts}` |

## `attach_trace(checkpointer, store=None)`

Envuelve `checkpointer.save` para que cada checkpoint también se registre en el
`GraphTraceStore`. **No cambia la firma ni el retorno** de `save`. Devuelve el store.

## `create_trace_router(store=None, path="/v1/studio/trace")`

Router FastAPI del trace. Requiere extra `server` (FastAPI).

| Ruta | Método | Descripción |
|------|--------|-------------|
| `{path}/runs` | `GET` | lista de runs (`?tenant=`) |
| `{path}/runs/{run_id}` | `GET` | pasos del run en orden |
| `{path}/runs/{run_id}/replay` | `GET` | estados reconstruidos step a step |
| `{path}/health` | `GET` | `{"status": "ok", "channel": "studio_trace"}` |

`ciel serve` lo monta en `/v1/studio/trace`; `ciel studio trace` lo imprime en
consola. Ver también la [guía de Ciel Studio](../guide/studio.md).
