# Referencia API — Ciel Studio: Cost (`ciel.studio_cost`)

Módulo: `ciel.studio_cost`. Dashboard de costos sobre el `CostGovernor`
existente (Fase 13 / F21). Offline-safe.

## `CostDashboardStore`

Store en memoria que acumula métricas de costo por tenant.

```python
from ciel.studio_cost import CostDashboardStore, attach_cost_tracking
from ciel.enterprise.cost import CostGovernor, ModelCost

governor = CostGovernor(
    models={"gpt-4o": ModelCost(per_1k_input=0.005, per_1k_output=0.015)},
    budgets={"*": 10.0},
)
dash = attach_cost_tracking(governor)

governor.record("acme", "gpt-4o", 1000, 500)  # también va al dashboard
summary = dash.summary(tenant_id="acme")
# {'total_usd': 0.0125, 'by_model': {'gpt-4o': 0.0125}, 'requests': 1, 'tenants': 1}
```

### Métodos

| Método | Descripción |
|--------|-------------|
| `record(tenant_id, model, input_tokens, output_tokens, amount)` | acumula un registro |
| `by_tenant(*, tenant_id=None)` | lista de `CostRecord` |
| `summary(*, tenant_id=None)` | `{total_usd, by_model, requests, tenants}` |
| `top_tenants(n=5)` | tenants por gasto descendente |

## `attach_cost_tracking(governor, store=None)`

Envuelve `governor.record` para que cada registro también se acumule en el
`CostDashboardStore` (usa `governor.estimate` para el monto). **No cambia la
firma ni el retorno** de `record`. Devuelve el store.

## `create_cost_router(store=None, path="/v1/studio/cost")`

Router FastAPI del cost dashboard. Requiere extra `server` (FastAPI).

| Ruta | Método | Descripción |
|------|--------|-------------|
| `{path}/summary` | `GET` | resumen (`?tenant=`) |
| `{path}/by-tenant` | `GET` | registros por tenant (`?tenant=`) |
| `{path}/top` | `GET` | top tenants (`?n=5`) |
| `{path}/health` | `GET` | `{"status": "ok", "channel": "studio_cost"}` |

`ciel serve` lo monta en `/v1/studio/cost`; `ciel studio cost` lo imprime en
consola. Ver también la [guía de Ciel Studio](../guide/studio.md).
