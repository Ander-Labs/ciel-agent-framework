"""Tests OFFLINE de F21 (Ciel Studio — cost dashboard sobre CostGovernor).

No requieren red ni LLM. Se construye un ``CostGovernor`` real y se verifica
que el ``CostDashboardStore`` acumula correctamente y que el router responde.
"""

from __future__ import annotations

from typing import Any

import pytest

from ciel.enterprise.cost import (
    BudgetExceededError,
    CostError,
    CostGovernor,
    ModelCost,
)
from ciel.studio_cost import (
    CostDashboardStore,
    attach_cost_tracking,
    create_cost_router,
    get_cost_store,
    reset_cost_store,
)


# ---------------------------------------------------------------------------
# (a) CostDashboardStore acumula y summary es correcto
# ---------------------------------------------------------------------------
def test_store_acumula_y_summary_correcto() -> None:
    store = CostDashboardStore()
    store.record("t1", "gpt-4o", 1000, 2000, 0.035)
    store.record("t1", "gpt-4o", 1000, 00, 0.005)
    store.record("t2", "gpt-3.5", 500, 500, 0.001)

    # by_tenant: todos y filtrado
    assert len(store.by_tenant()) == 3
    assert len(store.by_tenant("t1")) == 2
    assert len(store.by_tenant("t2")) == 1

    # summary global
    s = store.summary()
    assert s["total_usd"] == pytest.approx(0.041)
    assert s["requests"] == 3
    assert s["tenants"] == 2
    assert s["by_model"]["gpt-4o"] == pytest.approx(0.040)
    assert s["by_model"]["gpt-3.5"] == pytest.approx(0.001)

    # summary por tenant
    s1 = store.summary("t1")
    assert s1["total_usd"] == pytest.approx(0.040)
    assert s1["requests"] == 2
    assert s1["tenants"] == 1


# ---------------------------------------------------------------------------
# (b) attach_cost_tracking captura records de un CostGovernor real
# ---------------------------------------------------------------------------
def _make_governor() -> CostGovernor:
    return CostGovernor(
        models={"gpt-4o": ModelCost(0.005, 0.015)},
        budgets={"*": 10.0},
    )


def test_attach_captura_records_y_coincide_con_governor() -> None:
    gov = _make_governor()
    store = attach_cost_tracking(gov, store=CostDashboardStore())

    # 1000 in + 1000 out -> 0.005 + 0.015 = 0.020
    r1 = gov.record("t1", "gpt-4o", 1000, 1000)
    # 2000 in + 0 out -> 0.010 + 0 = 0.010
    r2 = gov.record("t1", "gpt-4o", 2000, 0)

    # record original sigue devolviendo el gasto actual del tenant
    assert r1 == pytest.approx(0.020)
    assert r2 == pytest.approx(0.030)

    # el store acumuló los dos registros
    assert len(store.by_tenant()) == 2
    assert store.summary("t1")["total_usd"] == pytest.approx(store.summary()["total_usd"])

    # el summary del store coincide con governor.spent
    assert store.summary("t1")["total_usd"] == pytest.approx(gov.spent("t1"))
    assert gov.spent("t1") == pytest.approx(0.030)


def test_attach_no_rompe_firma_ni_estimacion() -> None:
    gov = _make_governor()
    store = attach_cost_tracking(gov, store=CostDashboardStore())

    # estimate sigue lanzando CostError con modelo desconocido
    with pytest.raises(CostError):
        gov.estimate("desconocido", 1, 1)

    # record con modelo desconocido lanza CostError (delegado al original)
    with pytest.raises(CostError):
        gov.record("t1", "desconocido", 1, 1)

    # store NO debe haber registrado nada inválido
    assert len(store.by_tenant()) == 0


# ---------------------------------------------------------------------------
# (c) el router responde 200 con JSON de summary
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    create_cost_router.__globals__["_FASTAPI_AVAILABLE"] is False,
    reason="FastAPI no disponible",
)
def test_router_responde_200_summary() -> None:
    reset_cost_store()
    store = get_cost_store()
    store.record("t1", "gpt-4o", 1000, 1000, 0.02)
    store.record("t2", "gpt-4o", 2000, 0, 0.01)

    # TestClient de Starlette/FastAPI
    try:
        from fastapi.testclient import TestClient
    except Exception:  # pragma: no cover
        pytest.skip("TestClient no disponible")

    router = create_cost_router(store=store)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # health
    resp = client.get("/v1/studio/cost/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "channel": "cost"}

    # summary global
    resp = client.get("/v1/studio/cost/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_usd"] == pytest.approx(0.03)
    assert data["requests"] == 2
    assert data["tenants"] == 2

    # summary filtrado por tenant
    resp = client.get("/v1/studio/cost/summary?tenant=t1")
    assert resp.status_code == 200
    assert resp.json()["total_usd"] == pytest.approx(0.02)

    # by-tenant
    resp = client.get("/v1/studio/cost/by-tenant")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # top
    resp = client.get("/v1/studio/cost/top?n=5")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    reset_cost_store()


# ---------------------------------------------------------------------------
# (d) top_tenants ordena descendente
# ---------------------------------------------------------------------------
def test_top_tenants_ordena_descendente() -> None:
    store = CostDashboardStore()
    store.record("low", "m", 100, 0, 0.001)
    store.record("high", "m", 1000, 0, 0.050)
    store.record("mid", "m", 500, 0, 0.020)

    top = store.top_tenants(n=5)
    assert [t["tenant_id"] for t in top] == ["high", "mid", "low"]
    assert top[0]["total_usd"] == pytest.approx(0.050)

    # respeta n
    assert len(store.top_tenants(n=2)) == 2
    assert len(store.top_tenants(n=0)) == 0


def test_singleton_get_reset() -> None:
    reset_cost_store()
    a = get_cost_store()
    b = get_cost_store()
    assert a is b
    reset_cost_store()
    c = get_cost_store()
    assert c is not a
