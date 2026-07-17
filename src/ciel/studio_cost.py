"""Ciel Studio — dashboard de costos (Fase 13 / F21).

Expone, sin red ni providers reales, un panel de costos sobre el
``CostGovernor`` ya existente. Acumula métricas de gasto por tenant y las
sirve vía un router FastAPI que se integra en ``ciel serve``. Diseñado para
ser:

- **Offline-safe**: el store es en memoria, no requiere BD ni red.
- **Multitenant**: cada registro se aísla por ``tenant_id``.
- **Fachada**: se monta *sobre* el ``CostGovernor`` existente (no lo
  reemplaza): ``attach_cost_tracking`` envuelve ``record`` para duplicar el
  gasto en el dashboard sin romper su firma ni su valor de retorno.

El router ``/v1/studio/cost`` se sondea (polling) desde la UI de Ciel
Studio; los tests usan fakes.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # FastAPI es opcional en entornos mínimos.
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - depends on optional extra
    APIRouter = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Modelo de datos (en memoria)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CostRecord:
    """Un registro de gasto de una llamada a un modelo de un tenant."""

    tenant_id: str
    model: str
    input_tokens: int
    output_tokens: int
    amount: float
    ts: float = field(default_factory=time.time)


class CostDashboardStore:
    """Store en memoria que ACUMULA métricas de costo por tenant.

    Offline-safe: no persiste a disco ni requiere red. Para producción se
    puede sustituir por un ``MemoryStore`` remoto sin tocar la API.
    """

    def __init__(self) -> None:
        self._records: List[CostRecord] = []

    # --- registro ---------------------------------------------------------
    def record(
        self,
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        amount: float,
    ) -> CostRecord:
        """Registra un gasto y devuelve el ``CostRecord`` creado."""
        rec = CostRecord(
            tenant_id=tenant_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            amount=float(amount),
            ts=time.time(),
        )
        self._records.append(rec)
        return rec

    # --- consultas --------------------------------------------------------
    def by_tenant(self, tenant_id: Optional[str] = None) -> List[CostRecord]:
        """Devuelve los registros (de un tenant o de todos)."""
        if tenant_id is None:
            return list(self._records)
        return [r for r in self._records if r.tenant_id == tenant_id]

    def summary(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Resumen agregado de costo.

        Devuelve ``{total_usd, by_model, requests, tenants}`` donde:
          - ``total_usd``: suma de ``amount`` (filtrado por tenant).
          - ``by_model``: dict ``{model: usd}`` agregado por modelo.
          - ``requests``: nº de registros.
          - ``tenants``: nº de tenants distintos.
        """
        recs = self.by_tenant(tenant_id=tenant_id)
        total_usd = 0.0
        by_model: Dict[str, float] = {}
        tenants: set[str] = set()
        for r in recs:
            total_usd += r.amount
            by_model[r.model] = by_model.get(r.model, 0.0) + r.amount
            tenants.add(r.tenant_id)
        return {
            "total_usd": total_usd,
            "by_model": by_model,
            "requests": len(recs),
            "tenants": len(tenants),
        }

    def top_tenants(self, n: int = 5) -> List[Dict[str, Any]]:
        """Top ``n`` tenants por gasto total (orden descendente)."""
        totals: Dict[str, float] = {}
        for r in self._records:
            totals[r.tenant_id] = totals.get(r.tenant_id, 0.0) + r.amount
        ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {"tenant_id": tid, "total_usd": usd} for tid, usd in ordered[: max(0, n)]
        ]


# Singleton por proceso (la UI y el governor comparten el mismo store).
_DEFAULT_STORE: Optional[CostDashboardStore] = None


def get_cost_store() -> CostDashboardStore:
    """Devuelve el store de costo por defecto (singleton)."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = CostDashboardStore()
    return _DEFAULT_STORE


def reset_cost_store() -> None:
    """Reinicia el store por defecto (útil en tests)."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = None


# ---------------------------------------------------------------------------
# Enganche al CostGovernor (fachada, no rompe la API existente)
# ---------------------------------------------------------------------------
def attach_cost_tracking(
    governor: Any,
    store: Optional[CostDashboardStore] = None,
) -> CostDashboardStore:
    """Envuelve ``governor.record`` para duplicar cada gasto en el dashboard.

    Es una fachada: NO cambia la firma ni el valor de retorno de
    ``record`` (sigue devolviendo el gasto actual del tenant). Tras cada
    registro, acumula un ``CostRecord`` en el ``CostDashboardStore`` (por
    defecto el singleton de costo).

    Args:
        governor: instancia de ``ciel.enterprise.cost.CostGovernor``.
        store: ``CostDashboardStore`` opcional; si se omite usa el singleton.

    Returns:
        El store usado (para montarlo en el router).
    """
    st = store or get_cost_store()
    _orig_record = governor.record

    @functools.wraps(_orig_record)
    def _tracked_record(
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        # Calculamos el monto a partir del governor (estimate) para no
        # depender del estado interno; luego delegamos al record real.
        amount = governor.estimate(model, input_tokens, output_tokens)
        result = _orig_record(tenant_id, model, input_tokens, output_tokens)
        st.record(
            tenant_id=tenant_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            amount=amount,
        )
        return result

    governor.record = _tracked_record  # type: ignore[assignment]
    governor._cost_store = st  # type: ignore[attr-defined]
    return st


# ---------------------------------------------------------------------------
# Router FastAPI (Ciel Studio — costos)
# ---------------------------------------------------------------------------
def create_cost_router(
    store: Optional[CostDashboardStore] = None,
    path: str = "/v1/studio/cost",
):
    """Crea un router FastAPI que expone el dashboard de costos.

    Rutas:
        ``GET {path}/summary``    -> resumen agregado (filtro ``?tenant=``)
        ``GET {path}/by-tenant``  -> registros por tenant (filtro ``?tenant=``)
        ``GET {path}/top``        -> top tenants (``?n=5``)
        ``GET {path}/health``     -> ``{"status": "ok", "channel": "cost"}``

    Offline-safe: no requiere red; se sondea desde la UI.
    """
    if not _FASTAPI_AVAILABLE:  # pragma: no cover - depends on optional extra
        raise RuntimeError("FastAPI no disponible; instala el extra 'server' para ciel serve")

    st = store or get_cost_store()
    router = APIRouter()

    @router.get(f"{path}/summary")
    async def cost_summary(tenant: Optional[str] = None):
        return JSONResponse(st.summary(tenant_id=tenant))

    @router.get(f"{path}/by-tenant")
    async def cost_by_tenant(tenant: Optional[str] = None):
        recs = st.by_tenant(tenant_id=tenant)
        return JSONResponse(
            [
                {
                    "tenant_id": r.tenant_id,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "amount": r.amount,
                    "ts": r.ts,
                }
                for r in recs
            ]
        )

    @router.get(f"{path}/top")
    async def cost_top(n: int = 5):
        return JSONResponse(st.top_tenants(n=n))

    @router.get(f"{path}/health")
    async def cost_health():
        return JSONResponse({"status": "ok", "channel": "cost"})

    return router


__all__ = [
    "CostRecord",
    "CostDashboardStore",
    "get_cost_store",
    "reset_cost_store",
    "attach_cost_tracking",
    "create_cost_router",
]
