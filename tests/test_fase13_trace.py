"""Tests formales de la Fase 13 / F20: graph view + replay/time-travel.

Cubre la trazabilidad de ``GraphCheckpointStore`` (Ciel Studio trace):

- (a) ``GraphTraceStore`` registra checkpoints y lista runs ordenados.
- (b) ``attach_trace`` captura los ``save`` de un ``GraphCheckpointStore`` real
  con ``MemoryStore`` de backend (sin romper el save original).
- (c) el router ``/v1/studio/trace`` responde 200 con JSON de runs (TestClient
  sobre una ``FastAPI`` mínima que incluye el router; offline, sin red).
- (d) el endpoint de replay devuelve la lista de estados step a step.

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). OFFLINE-SAFE.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ciel.orchestration.graph import GraphCheckpointStore, GraphState, StateGraph
from ciel.runtime.memory import MemoryStore
from ciel.studio_trace import (
    GraphTraceStore,
    attach_trace,
    create_trace_router,
    get_trace_store,
    get_trace_summary,
    reset_trace_store,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


def _build_linear_graph():
    """Grafo entry -> a -> b -> finish para ejecutar pasos y generar checkpoints."""

    def a(state_data: Dict[str, Any]) -> str:
        state_data["a_ran"] = True
        return "out-a"

    def b(state_data: Dict[str, Any]) -> str:
        state_data["b_ran"] = True
        return "out-b"

    def finish(state_data: Dict[str, Any]) -> str:
        state_data["finish_ran"] = True
        return "out-finish"

    g = StateGraph(name="trace-demo")
    g.add_node("a", a)
    g.add_node("b", b)
    g.add_node("finish", finish)
    g.add_edge("a", "b")
    g.add_edge("b", "finish")
    g.set_entry_point("a")
    g.set_finish_point("finish")
    return g


def _make_app() -> FastAPI:
    """App mínima FastAPI que monta únicamente el router de trace (offline)."""
    app = FastAPI()
    app.include_router(create_trace_router())
    return app


# --------------------------------------------------------------------------- #
# (a) GraphTraceStore registra checkpoints y lista runs ordenados
# --------------------------------------------------------------------------- #
def test_trace_store_records_checkpoints_and_lists_runs_ordered():
    reset_trace_store()
    store = GraphTraceStore()
    store.record_checkpoint(
        {
            "run_id": "r1",
            "step_index": 0,
            "tenant_id": "t1",
            "session_id": "s1",
            "paused": False,
            "paused_node": None,
            "finished": False,
            "state_snapshot": {"visited": ["a"]},
        }
    )
    store.record_checkpoint(
        {
            "run_id": "r1",
            "step_index": 1,
            "tenant_id": "t1",
            "session_id": "s1",
            "paused": False,
            "paused_node": None,
            "finished": True,
            "state_snapshot": {"visited": ["a", "b"]},
        }
    )
    store.record_checkpoint(
        {
            "run_id": "r2",
            "step_index": 0,
            "tenant_id": "t2",
            "session_id": "s2",
            "paused": True,
            "paused_node": "a",
            "finished": False,
            "state_snapshot": {"visited": []},
        }
    )

    # list_runs devuelve ambos runs como resúmenes.
    runs = store.list_runs()
    assert len(runs) == 2
    assert {r["run_id"] for r in runs} == {"r1", "r2"}

    # Filtro por tenant.
    t1_runs = store.list_runs(tenant_id="t1")
    assert [r["run_id"] for r in t1_runs] == ["r1"]

    # steps ordenados por step_index dentro de un run.
    run1 = store.get_run("r1")
    assert run1 is not None
    assert [s["step_index"] for s in run1["steps"]] == [0, 1]
    assert run1["finished"] is True
    assert run1["step_count"] == 2

    # get_run con tenant incorrecto -> None.
    assert store.get_run("r1", tenant_id="t2") is None

    # snapshot trae counts.
    snap = store.snapshot()
    assert snap["counts"]["runs"] == 2
    assert snap["counts"]["finished_runs"] == 1
    assert snap["counts"]["paused_runs"] == 1


def test_trace_store_steps_of_returns_ordered():
    store = GraphTraceStore()
    # Insertamos fuera de orden a propósito.
    store.record_checkpoint({"run_id": "rx", "step_index": 2, "state_snapshot": {"v": 2}})
    store.record_checkpoint({"run_id": "rx", "step_index": 0, "state_snapshot": {"v": 0}})
    store.record_checkpoint({"run_id": "rx", "step_index": 1, "state_snapshot": {"v": 1}})
    steps = store.steps_of("rx")
    assert [s.step_index for s in steps] == [0, 1, 2]
    assert [s.state_snapshot["v"] for s in steps] == [0, 1, 2]


# --------------------------------------------------------------------------- #
# (b) attach_trace captura los save de un GraphCheckpointStore real
# --------------------------------------------------------------------------- #
def test_attach_trace_captures_saves_from_real_checkpointer():
    store, path = _make_store()
    try:
        reset_trace_store()
        trace = GraphTraceStore()
        checkpointer = GraphCheckpointStore(store)
        returned = attach_trace(checkpointer, store=trace)
        assert returned is trace

        # El save original sigue funcionando y devuelve checkpoint_id.
        st = GraphState(data={"x": 1})
        cid = checkpointer.save(
            run_id="run-real",
            step_index=0,
            state=st,
            finished=False,
            tenant_id="t1",
            session_id="s1",
        )
        assert isinstance(cid, str) and len(cid) > 0

        # El save original persiste en MemoryStore (no lo rompimos).
        loaded = checkpointer.load(
            run_id="run-real", tenant_id="t1", session_id="s1"
        )
        assert loaded is not None
        assert loaded["state"]["data"]["x"] == 1

        # attach_trace registró el checkpoint con el snapshot del GraphState.
        run = trace.get_run("run-real")
        assert run is not None
        assert run["step_count"] == 1
        step = run["steps"][0]
        assert step["checkpoint_id"] == cid
        assert step["state_snapshot"]["data"]["x"] == 1
        assert step["tenant_id"] == "t1"
    finally:
        store.conn.close()  # libera el handle SQLite antes de borrar el archivo
        os.remove(path)


def test_attach_trace_captures_full_run_producing_ordered_steps():
    store, path = _make_store()
    try:
        reset_trace_store()
        trace = GraphTraceStore()
        checkpointer = GraphCheckpointStore(store)
        attach_trace(checkpointer, store=trace)

        g = _build_linear_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1", session_id="s-run")

        asyncio.run(runner.run(run_id="run-full"))

        # La ejecución completa (a -> b -> finish) genera checkpoints por paso.
        run = trace.get_run("run-full")
        assert run is not None
        assert run["finished"] is True
        # a(1) + b(2) + finish(3) => 3 pasos guardados por el runner.
        assert run["step_count"] == 3
        assert [s["step_index"] for s in run["steps"]] == [1, 2, 3]
        # El replay reconstruye 3 estados step a step.
        states = trace.replay("run-full")
        assert states is not None
        assert len(states) == 3
        assert states[-1]["visited"] == ["a", "b", "finish"]
    finally:
        store.conn.close()  # libera el handle SQLite antes de borrar el archivo
        os.remove(path)


# --------------------------------------------------------------------------- #
# (c) El router responde 200 con JSON de runs (offline, TestClient)
# --------------------------------------------------------------------------- #
def test_trace_router_health_and_runs_200():
    reset_trace_store()
    trace = GraphTraceStore()
    trace.record_checkpoint(
        {
            "run_id": "r-router",
            "step_index": 0,
            "tenant_id": "t1",
            "session_id": "s1",
            "finished": True,
            "state_snapshot": {"visited": ["a"]},
        }
    )
    app = FastAPI()
    app.include_router(create_trace_router(store=trace))

    client = TestClient(app)

    # health
    h = client.get("/v1/studio/trace/health")
    assert h.status_code == 200
    assert h.json() == {"status": "ok", "channel": "trace"}

    # snapshot
    snap = client.get("/v1/studio/trace")
    assert snap.status_code == 200
    assert snap.json()["counts"]["runs"] == 1

    # runs
    runs = client.get("/v1/studio/trace/runs")
    assert runs.status_code == 200
    body = runs.json()
    assert isinstance(body, list)
    assert body[0]["run_id"] == "r-router"

    # runs filtrado por tenant
    runs_t2 = client.get("/v1/studio/trace/runs", params={"tenant": "t2"})
    assert runs_t2.status_code == 200
    assert runs_t2.json() == []


def test_trace_router_run_detail_200_and_404():
    reset_trace_store()
    trace = GraphTraceStore()
    trace.record_checkpoint(
        {
            "run_id": "r-detail",
            "step_index": 0,
            "tenant_id": "t1",
            "session_id": "s1",
            "finished": False,
            "state_snapshot": {"visited": []},
        }
    )
    app = FastAPI()
    app.include_router(create_trace_router(store=trace))
    client = TestClient(app)

    ok = client.get("/v1/studio/trace/runs/r-detail")
    assert ok.status_code == 200
    assert ok.json()["run_id"] == "r-detail"
    assert ok.json()["step_count"] == 1

    missing = client.get("/v1/studio/trace/runs/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"] == "run_not_found"


# --------------------------------------------------------------------------- #
# (d) El endpoint de replay devuelve la lista de estados step a step
# --------------------------------------------------------------------------- #
def test_trace_router_replay_returns_states_step_by_step():
    reset_trace_store()
    trace = GraphTraceStore()
    trace.record_checkpoint(
        {
            "run_id": "r-replay",
            "step_index": 0,
            "state_snapshot": {"visited": ["a"]},
        }
    )
    trace.record_checkpoint(
        {
            "run_id": "r-replay",
            "step_index": 1,
            "state_snapshot": {"visited": ["a", "b"]},
        }
    )
    trace.record_checkpoint(
        {
            "run_id": "r-replay",
            "step_index": 2,
            "state_snapshot": {"visited": ["a", "b", "finish"]},
        }
    )
    app = FastAPI()
    app.include_router(create_trace_router(store=trace))
    client = TestClient(app)

    resp = client.get("/v1/studio/trace/runs/r-replay/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r-replay"
    steps = body["steps"]
    assert len(steps) == 3
    # time-travel: el estado crece paso a paso.
    assert steps[0]["visited"] == ["a"]
    assert steps[1]["visited"] == ["a", "b"]
    assert steps[2]["visited"] == ["a", "b", "finish"]

    missing = client.get("/v1/studio/trace/runs/nope/replay")
    assert missing.status_code == 404


def test_get_trace_summary_autonomous_from_singleton():
    reset_trace_store()
    st = get_trace_store()
    st.record_checkpoint(
        {"run_id": "r-sum", "step_index": 0, "tenant_id": "t1", "state_snapshot": {}}
    )
    summary = get_trace_summary()
    assert summary["counts"]["runs"] == 1
    # El summary es autónomo: no requiere studio.py.
    assert "runs" in summary


__all__ = [
    "test_trace_store_records_checkpoints_and_lists_runs_ordered",
    "test_trace_store_steps_of_returns_ordered",
    "test_attach_trace_captures_saves_from_real_checkpointer",
    "test_attach_trace_captures_full_run_producing_ordered_steps",
    "test_trace_router_health_and_runs_200",
    "test_trace_router_run_detail_200_and_404",
    "test_trace_router_replay_returns_states_step_by_step",
    "test_get_trace_summary_autonomous_from_singleton",
]
