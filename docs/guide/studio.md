# Ciel Studio — dashboard de observabilidad (Fase 13 / F19)

`ciel studio` es el panel mínimo operativo de Ciel: muestra, sin red ni
providers reales, lo que el agente está haciendo — **sesiones**, **loops** y
**estado**. Es la base de *Ciel Studio* (Web UI + observabilidad visual).

> **Offline-safe:** el store es en memoria; no requiere BD ni red. Para
> producción se puede sustituir por un `MemoryStore` remoto sin tocar la API.

## Qué hace

- `StudioStore` — store en memoria que registra sesiones (prompt, respuesta,
  nº de tool-calls, turns) y loops, aislados por `tenant_id`.
- `install_studio_support(agent)` — envuelve `agent.run`/`agent.arun` para
  registrar cada ejecución en el store. **No cambia la firma ni el valor de
  retorno** del `Agent`.
- `create_studio_router(store)` — router FastAPI `GET /v1/studio` que
  expone el snapshot (sondeable desde una UI).
- `ciel serve` monta el dashboard automáticamente en `/v1/studio`.
- `ciel studio show` imprime el snapshot en consola.

## Uso rápido

```python
import ciel
from ciel import Agent, install_studio_support, get_studio_store

agent = Agent(model="gpt-4o-mini", tools=[...])
install_studio_support(agent)  # empieza a registrar sesiones

agent.run("Suma 2 + 3", tenant_id="acme")
agent.run("¿Cuál es el clima?", tenant_id="acme")

# Inspección en consola:
store = get_studio_store()
print(store.snapshot(tenant_id="acme"))
# {'sessions': [...], 'loops': [...], 'counts': {...}}
```

## Desde la CLI

```bash
# 1) Arranca el gateway (monta /v1/studio)
ciel serve

# 2) En otra terminal, mientras el agente corre, mira el dashboard:
ciel studio show
ciel studio show --tenant acme
```

El endpoint `GET /v1/studio` devuelve JSON:

```json
{
  "sessions": [{"id": "sess-...", "type": "session", "tenant_id": "acme",
                "agent": "ciel-agent", "prompt": "...", "text": "...",
                "finish_reason": "stop", "tool_calls": 0, "turns": 1}],
  "loops": [],
  "counts": {"sessions": 1, "loops": 0, "running_loops": 0}
}
```

## API

| Símbolo | Descripción |
|----------|-------------|
| `StudioStore` | store en memoria multitenant (`record_session`, `record_loop`, `snapshot`) |
| `get_studio_store()` | singleton de studio (compartido con `ciel serve`) |
| `install_studio_support(agent, store=None)` | registra sesiones tras cada `run`/`arun` |
| `create_studio_router(store=None, path="/v1/studio")` | router FastAPI del dashboard |

Consulta también la [referencia API de Studio](../api-reference/studio.md).
