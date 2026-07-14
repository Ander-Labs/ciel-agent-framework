"""Tests para el módulo de Flows event-driven (Fase 5, estilo CrewAI.Flows).

Cubre: flow lineal (start -> listen -> listen), router con selección de UNA
rama, checkpointer + resume tras interrupción, validación de routers (en
compile y en runtime) y el guard de ``max_steps``.

Patrón: funciones ``def test_*`` síncronas que envuelven la corutina con
``asyncio.run`` (sin pytest-asyncio). Los pasos reciben el ``FlowState``
mutable y escriben en ``state.data``; el runner guarda ``state.results[sid]``
y ``state.data['__out__'][sid]``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from ciel.orchestration import (
    Flow,
    FlowCheckpointStore,
    FlowError,
    FlowState,
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
# 1. Flow lineal (start -> listen -> listen) ejecuta en orden
# --------------------------------------------------------------------------- #
def test_linear_flow_executes_in_order():
    def s(state):
        state.data["s"] = "start"
        return "os"

    def l1(state):
        state.data["l1"] = "l1"
        return "ol1"

    def l2(state):
        state.data["l2"] = "l2"
        return "ol2"

    flow = Flow(name="linear")
    flow.add_start(s)
    flow.add_listen("s", l1)
    flow.add_listen("l1", l2)

    runner = flow.compile()
    state = asyncio.run(runner.run())

    # Se ejecutaron en orden y dejaron sus salidas.
    assert state.completed == ["s", "l1", "l2"]
    assert state.results["s"] == "os"
    assert state.results["l1"] == "ol1"
    assert state.results["l2"] == "ol2"
    assert state.data["__out__"]["s"] == "os"
    assert state.data["__out__"]["l2"] == "ol2"
    assert state.data["s"] == "start"
    assert state.data["l2"] == "l2"


# --------------------------------------------------------------------------- #
# 2. Router: según el valor se activa UNA rama (la otra NO)
# --------------------------------------------------------------------------- #
def test_router_activates_only_one_branch():
    def s(state):
        return "init"

    def decide(state):
        state.data["route"] = "left"
        return "left"

    def branch_left(state):
        state.data["result"] = "LEFT"
        return "bl"

    def branch_right(state):
        state.data["result"] = "RIGHT"
        return "br"

    # ORDEN: registra las ramas ANTES del router, y el router antes de compile.
    flow = Flow(name="router")
    flow.add_start(s)
    flow.add_branch(branch_left)
    flow.add_branch(branch_right)
    flow.add_router("s", decide, {"left": "branch_left", "right": "branch_right"})

    runner = flow.compile()
    state = asyncio.run(runner.run())

    # El router activó EXACTAMENTE la rama "left".
    assert state.completed == ["s", "decide", "branch_left"]
    assert state.data["result"] == "LEFT"
    assert state.results["branch_left"] == "bl"
    # La otra rama NO se ejecutó.
    assert "branch_right" not in state.completed
    assert "branch_right" not in state.results
    assert "branch_right" not in state.data["__out__"]


# --------------------------------------------------------------------------- #
# 3. Checkpointer + resume tras interrupción (análogo a test_graph)
# --------------------------------------------------------------------------- #
def test_resume_after_interruption_with_checkpointer():
    store, path = _make_store()
    try:
        checkpointer = FlowCheckpointStore(store)
        run_id = "flow-resume-1"

        # El paso "boom" falla en sus primeras invocaciones (cubre los
        # reintentos del Supervisor durante run #1) y se recupera a partir de
        # la siguiente. Así run() lanza FlowError, pero resume() —que
        # re-ejecuta el último paso completado (boom)— lo encuentra ya
        # recuperado.
        calls = {"n": 0}

        def s(state):
            state.data.setdefault("log", []).append("s")
            return "os"

        def b(state):
            state.data.setdefault("log", []).append("b")
            return "ob"

        def boom(state):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("boom on first run")
            state.data.setdefault("log", []).append("boom")
            return "recovered"

        def finish(state):
            state.data.setdefault("log", []).append("finish")
            return "of"

        flow = Flow(name="resume")
        flow.add_start(s)
        flow.add_listen("s", b)
        flow.add_listen("b", boom)
        flow.add_listen("boom", finish)

        # Primera ejecución: falla en "boom" (tras checkpoint de s y b).
        runner1 = flow.compile(checkpointer=checkpointer)
        with pytest.raises(FlowError):
            asyncio.run(runner1.run(run_id=run_id))

        # Debe existir un checkpoint persistido con s y b ya completados.
        ckpt = checkpointer.load(run_id=run_id, tenant_id=None, session_id=None)
        assert ckpt is not None
        assert ckpt["state"]["completed"] == ["s", "b"]
        assert ckpt["finished"] is False

        # Nuevo runner, mismo checkpointer y run_id: reanuda.
        runner2 = flow.compile(checkpointer=checkpointer)
        state = asyncio.run(runner2.resume(run_id=run_id))

        # Continuó más allá de la interrupción y terminó.
        assert "boom" in state.completed
        assert "finish" in state.completed
        assert state.data["__out__"]["boom"] == "recovered"
        assert state.data["__out__"]["finish"] == "of"
        assert state.results["boom"] == "recovered"
        assert state.data["log"] == ["s", "b", "boom", "finish"]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 4a. Router cuyo target de rama no está registrado -> FlowError en compile
# --------------------------------------------------------------------------- #
def test_router_with_unregistered_branch_target_raises_on_compile():
    def s(state):
        return "init"

    def decide(state):
        return "left"

    flow = Flow(name="bad-compile")
    flow.add_start(s)
    # "ghost" no está registrado como paso -> debe fallar en compile().
    flow.add_router("s", decide, {"left": "ghost"})

    with pytest.raises(FlowError):
        flow.compile()


# --------------------------------------------------------------------------- #
# 4b. Router que devuelve clave sin rama -> FlowError en runtime
# --------------------------------------------------------------------------- #
def test_router_returns_unknown_key_raises_flow_error():
    def s(state):
        return "init"

    def decide(state):
        return "unknown"  # no está en branches

    def branch_left(state):
        return "bl"

    flow = Flow(name="bad-runtime")
    flow.add_start(s)
    flow.add_branch(branch_left)
    flow.add_router("s", decide, {"left": "branch_left"})

    runner = flow.compile()
    with pytest.raises(FlowError):
        asyncio.run(runner.run())


# --------------------------------------------------------------------------- #
# 5. Guard de max_steps -> FlowError (cadena más larga que max_steps)
# --------------------------------------------------------------------------- #
def test_max_steps_guard_raises_on_exceeding_limit():
    def make(i):
        def step(state):
            state.data.setdefault("chain", []).append(i)
            return f"o{i}"
        step.__name__ = f"step{i}"
        return step

    flow = Flow(name="maxsteps")
    flow.add_start(make(0))
    flow.add_listen("step0", make(1))
    flow.add_listen("step1", make(2))
    flow.add_listen("step2", make(3))
    flow.add_listen("step3", make(4))

    # 5 pasos en cadena pero max_steps=3 -> debe detenerse con FlowError.
    # El guard salta tras completar 3 pasos (idx >= max_steps), así que
    # step3 y step4 nunca llegan a ejecutarse.
    runner = flow.compile(max_steps=3)
    with pytest.raises(FlowError) as excinfo:
        asyncio.run(runner.run())

    msg = str(excinfo.value)
    assert "max_steps" in msg
