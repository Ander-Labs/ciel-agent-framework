"""Tests para el módulo de grafo de estado (Fase 5).

Cubre: grafo lineal, aristas condicionales, reanudación tras interrupción
con checkpoint, time-travel (run_from), validación de entry point y
propagación de fallos del Supervisor.

Sigue el patrón de los tests existentes del proyecto: funciones ``def test_*``
síncronas que envuelven la corutina con ``asyncio.run`` (sin marcadores de
pytest-asyncio). No se inventan fixtures.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from ciel.orchestration.supervisor import Supervisor
from ciel.orchestration.graph import (
    GraphCheckpointStore,
    GraphError,
    GraphState,
    StateGraph,
)
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


# --------------------------------------------------------------------------- #
# 1. Grafo lineal (entry -> a -> b -> finish)
# --------------------------------------------------------------------------- #
def test_linear_graph_executes_in_order():
    async def a(state_data):
        state_data["a_ran"] = True
        return "out-a"

    async def b(state_data):
        state_data["b_ran"] = True
        return "out-b"

    async def finish(state_data):
        state_data["finish_ran"] = True
        return "out-finish"

    g = StateGraph(name="linear")
    g.add_node("a", a)
    g.add_node("b", b)
    g.add_node("finish", finish)
    g.add_edge("a", "b")
    g.add_edge("b", "finish")
    g.set_entry_point("a")
    g.set_finish_point("finish")

    runner = g.compile()
    state = asyncio.run(runner.run(initial_data={"seed": 1}))

    # Los nodos se ejecutaron y dejaron sus salidas.
    assert state.data["__out__a"] == "out-a"
    assert state.data["__out__b"] == "out-b"
    assert state.data["__out__finish"] == "out-finish"

    # a y b se visitaron, en ese orden, antes del punto de fin.
    assert "a" in state.visited and "b" in state.visited
    assert state.visited.index("a") < state.visited.index("b")
    assert state.visited[:2] == ["a", "b"]
    assert state.current_node == "finish"  # terminó en el finish


# --------------------------------------------------------------------------- #
# 2. Grafo con aristas condicionales (router -> branch)
# --------------------------------------------------------------------------- #
def test_conditional_edges_choose_branch():
    async def router(state_data):
        state_data["branch"] = "left"
        return "routed"

    async def left(state_data):
        state_data["taken"] = "left"
        return "out-left"

    async def right(state_data):
        state_data["taken"] = "right"
        return "out-right"

    async def finish(state_data):
        return "done"

    g = StateGraph(name="cond")
    g.add_node("router", router)
    g.add_node("left", left)
    g.add_node("right", right)
    g.add_node("finish", finish)
    # Cada target con su propia guarda booleana sobre state.data.
    g.add_conditional_edges("router", ["left"], lambda d, c="left": d["branch"] == c)
    g.add_conditional_edges("router", ["right"], lambda d, c="right": d["branch"] == c)
    g.add_edge("left", "finish")
    g.add_edge("right", "finish")
    g.set_entry_point("router")
    g.set_finish_point("finish")

    runner = g.compile()
    state = asyncio.run(runner.run())

    # Se tomó la rama "left" y NO la "right".
    assert state.data["taken"] == "left"
    assert state.data["__out__left"] == "out-left"
    assert "left" in state.visited
    assert "right" not in state.visited
    assert "__out__right" not in state.data


# --------------------------------------------------------------------------- #
# 3. Reanudación tras interrupción (checkpoint + resume)
# --------------------------------------------------------------------------- #
def test_resume_after_interruption_with_checkpointer():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        run_id = "resume-run-1"

        # El nodo "boom" falla en sus primeras invocaciones (cubre los
        # reintentos del Supervisor durante run #1) y se recupera a partir de
        # la siguiente. Así run() lanza GraphError, pero resume() —que
        # re-ejecuta el último nodo visitado (b) y luego boom— lo encuentra
        # ya recuperado.
        calls = {"n": 0}

        async def a(state_data):
            state_data.setdefault("log", []).append("a")
            return "oa"

        async def b(state_data):
            state_data.setdefault("log", []).append("b")
            return "ob"

        async def boom(state_data):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("boom on first run")
            state_data.setdefault("log", []).append("boom")
            return "recovered"

        async def finish(state_data):
            state_data.setdefault("log", []).append("finish")
            return "of"

        g = StateGraph(name="resume")
        g.add_node("a", a)
        g.add_node("b", b)
        g.add_node("boom", boom)
        g.add_node("finish", finish)
        g.add_edge("a", "b")
        g.add_edge("b", "boom")
        g.add_edge("boom", "finish")
        g.set_entry_point("a")
        g.set_finish_point("finish")

        # Primera ejecución: falla en "boom" (tras checkpoint de a y b).
        runner1 = g.compile(checkpointer=checkpointer)
        with pytest.raises(GraphError):
            asyncio.run(runner1.run(run_id=run_id))

        # Debe existir un checkpoint persistido con a y b ya visitados.
        ckpt = checkpointer.load(run_id=run_id, tenant_id=None, session_id=None)
        assert ckpt is not None
        assert ckpt["state"]["visited"] == ["a", "b"]

        # Nuevo runner, mismo checkpointer y run_id: reanuda.
        runner2 = g.compile(checkpointer=checkpointer)
        state = asyncio.run(runner2.resume(run_id=run_id))

        # Continuó más allá de la interrupción y terminó. Al finalizar,
        # current_node queda en el nodo finish (no en None), igual que run().
        assert "boom" in state.visited
        assert "finish" in state.visited
        assert state.data["__out__boom"] == "recovered"
        assert state.data["__out__finish"] == "of"
        assert state.current_node == "finish"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 4. Time-travel: run_from se detiene en up_to_node
# --------------------------------------------------------------------------- #
def test_run_from_stops_at_target_node():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        run_id = "timetravel-1"

        async def a(state_data):
            return "oa"

        async def b(state_data):
            return "ob"

        async def c(state_data):
            return "oc"

        async def finish(state_data):
            return "of"

        g = StateGraph(name="tt")
        g.add_node("a", a)
        g.add_node("b", b)
        g.add_node("c", c)
        g.add_node("finish", finish)
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "finish")
        g.set_entry_point("a")
        g.set_finish_point("finish")

        runner = g.compile(checkpointer=checkpointer)
        state = asyncio.run(runner.run_from(run_id=run_id, up_to_node="b"))

        # Se detiene exactamente en "b".
        assert state.current_node == "b"
        assert state.visited == ["a", "b"]
        assert "c" not in state.visited
        assert "finish" not in state.visited
        # Solo ejecutó hasta b.
        assert "__out__a" in state.data
        assert "__out__b" in state.data
        assert "__out__c" not in state.data
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 5. Grafo sin entry point lanza GraphError al compilar
# --------------------------------------------------------------------------- #
def test_compile_without_entry_point_raises():
    async def a(state_data):
        return "x"

    g = StateGraph(name="no-entry")
    g.add_node("a", a)

    with pytest.raises(GraphError):
        g.compile()


# --------------------------------------------------------------------------- #
# 6. Nodo que falla siempre propaga GraphError (Supervisor reintenta)
# --------------------------------------------------------------------------- #
def test_node_always_failing_propagates_graph_error():
    async def boom(state_data):
        raise RuntimeError("boom always")

    g = StateGraph(name="fail")
    g.add_node("boom", boom)
    g.add_node("finish", lambda d: "never")
    g.add_edge("boom", "finish")
    g.set_entry_point("boom")
    g.set_finish_point("finish")

    # Supervisor con max_attempts=2: debe reintentar 2 veces y luego propagar.
    runner = g.compile(supervisor=Supervisor(max_attempts=2, timeout_s=1.0))

    with pytest.raises(GraphError) as excinfo:
        asyncio.run(runner.run())

    msg = str(excinfo.value)
    assert "boom always" in msg
    assert "boom" in msg
    # El Supervisor agotó los reintentos.
    assert "2 attempts" in msg
