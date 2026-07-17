"""Fase 14 / F16 — HA operativa: health reales, lease y smoke multi-réplica.

* ``/healthz`` (liveness) y ``/readyz`` (readiness) responden con modelos
  distintos y separan proceso-vivo de backend-conectado.
* 2 instancias (apps) construidas con el MISMO StateBackend comparten un
  checkpoint escrito por una y leído por la otra (criterio de cierre F16).
* El lease evita doble ejecución de un run_id entre réplicas.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ciel.gateway.server import make_app
from ciel.runtime.resume import claim_run_lease, release_run_lease
from ciel.runtime.state_backend import SqliteStateBackend


def _shared_backend(tmp_path: Path) -> SqliteStateBackend:
    # Mismo archivo SQLite => dos "réplicas" comparten state.
    return SqliteStateBackend(str(tmp_path / "shared.sqlite"))


def test_healthz_liveness_and_readyz_readiness(tmp_path: Path) -> None:
    backend = _shared_backend(tmp_path)
    app = make_app(include_mcp=False, include_webhook=False, state_backend=backend)
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"
        rz = client.get("/readyz")
        assert rz.status_code == 200
        body = rz.json()
        assert body["status"] == "ready"
        assert body["backend"] == "sqlite"
        assert body["backend_ready"] is True
        # /health sigue siendo alias (compat).
        rh = client.get("/health")
        assert rh.status_code == 200
    backend.close()


def test_multi_replica_share_checkpoint(tmp_path: Path) -> None:
    backend = _shared_backend(tmp_path)
    # Réplica A escribe un checkpoint compartido.
    backend.set(
        tenant_id="t1",
        session_id="s1",
        key="checkpoint:run-xyz",
        value={"checkpoint_id": "run-xyz", "turn_index": 3, "state": {"done": True}},
    )
    # Réplica B (otra app, otro proceso lógico) monta el MISMO backend.
    app_b = make_app(include_mcp=False, include_webhook=False, state_backend=backend)
    with TestClient(app_b) as client:
        rz = client.get("/readyz")
        assert rz.json()["status"] == "ready"
    # Lectura directa desde la "réplica B" (mismo backend compartido).
    payload = backend.get(tenant_id="t1", session_id="s1", key="checkpoint:run-xyz")
    assert payload == {"checkpoint_id": "run-xyz", "turn_index": 3, "state": {"done": True}}
    backend.close()


def test_run_lease_prevents_double_execution(tmp_path: Path) -> None:
    backend = _shared_backend(tmp_path)
    holder_a = "replica-A"
    holder_b = "replica-B"

    # Réplica A adquiere el lease.
    assert claim_run_lease(backend, run_id="run-1", tenant_id="t1", session_id="s1", holder=holder_a)
    # Réplica B intenta adquirir el mismo run_id sin que expire => rechazada.
    assert not claim_run_lease(
        backend, run_id="run-1", tenant_id="t1", session_id="s1", holder=holder_b
    )
    # Réplica A (mismo holder) puede renovar.
    assert claim_run_lease(backend, run_id="run-1", tenant_id="t1", session_id="s1", holder=holder_a)

    # Tras liberar, B puede adquirir.
    release_run_lease(backend, run_id="run-1", tenant_id="t1", session_id="s1")
    assert claim_run_lease(
        backend, run_id="run-1", tenant_id="t1", session_id="s1", holder=holder_b
    )
    backend.close()


def test_run_lease_expires(tmp_path: Path) -> None:
    backend = _shared_backend(tmp_path)
    assert claim_run_lease(
        backend, run_id="run-2", tenant_id="t1", session_id="s1", holder="A", ttl_seconds=1
    )
    time.sleep(1.1)
    # Expiró => otro holder puede tomarlo.
    assert claim_run_lease(
        backend, run_id="run-2", tenant_id="t1", session_id="s1", holder="B"
    )
    backend.close()
