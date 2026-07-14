"""Tests para la Agencia autónoma en bucle (Fase 6).

Cubre el modelo ``Task``, el ``EventLoop`` durable con reintentos
exponenciales y checkpoint (``EventLoopCheckpointStore`` + ``resume``),
y el orquestador de alto nivel ``AutonomousAgent`` (descomposición de
objetivos en tareas + integración con ``SessionStore``).

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). Para los stores sobre
SQLite se libera el lock en Windows con ``store.close()`` antes de
``os.remove``. OFFLINE-SAFE: los handlers son funciones locales.

NOTA: las firmas reales del core (keyword-only) se respetan EXACTAMENTE:
``EventLoopCheckpointStore.save(*, run_id, loop_state, task, tenant_id, session_id)``,
``.load(*, run_id, tenant_id, session_id)`` y ``EventLoop.resume(*, run_id, handler)``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict, List

import pytest

from ciel.orchestration.agent import (
    AgentError,
    AutonomousAgent,
    EventLoop,
    EventLoopCheckpointStore,
    EventLoopError,
    EventLoopStep,
    Task,
    TaskError,
)
from ciel.orchestration.session import SessionStore
from ciel.orchestration.supervisor import Supervisor
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return MemoryStore(path), path


# --------------------------------------------------------------------------- #
# 1. Task.snapshot / from_snapshot round-trip preserva todos los campos
# --------------------------------------------------------------------------- #
def test_task_snapshot_roundtrip_preserves_fields():
    import time

    task = Task(
        goal="resolver el problema",
        payload={"k": "v", "n": 3},
        status="running",
        attempts=2,
        result={"ok": True},
        error=None,
    )
    snap = task.snapshot()
    restored = Task.from_snapshot(snap)

    assert restored.id == task.id
    assert restored.goal == task.goal
    assert restored.payload == task.payload
    assert restored.status == task.status
    assert restored.attempts == task.attempts
    assert restored.result == task.result
    assert restored.error == task.error
    # Los timestamps se preservan (round-trip completo).
    assert restored.created_at == task.created_at
    assert restored.updated_at == task.updated_at


# --------------------------------------------------------------------------- #
# 2. EventLoop.run completa una tarea en 1 intento (handler que devuelve dict)
# --------------------------------------------------------------------------- #
def test_event_loop_run_completes_in_one_attempt():
    def handler(task: Task) -> Dict[str, Any]:
        return {"echo": task.goal}

    loop = EventLoop(
        supervisor=Supervisor(max_attempts=1),
        max_attempts=3,
        base_delay_s=0.001,
    )
    task = Task(goal="tarea-unica")
    result = asyncio.run(loop.run(task, handler))

    assert result.status == "succeeded"
    assert result.attempts == 1
    assert result.result == {"echo": "tarea-unica"}


# --------------------------------------------------------------------------- #
# 3. EventLoop.run con reintento exponencial: falla N veces y luego tiene éxito
# --------------------------------------------------------------------------- #
def test_event_loop_run_exponential_retry_then_success():
    calls = {"n": 0}

    def handler(task: Task) -> Dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"fallo temporal #{calls['n']}")
        return {"ok": True, "intentos": calls["n"]}

    loop = EventLoop(
        supervisor=Supervisor(max_attempts=1),
        max_attempts=5,
        base_delay_s=0.001,
    )
    task = Task(goal="reintentable")
    result = asyncio.run(loop.run(task, handler))

    # Falló en los intentos 1 y 2 (raise), éxito en el intento 3.
    assert result.status == "succeeded"
    assert result.attempts == 3, f"esperaba 3 intentos, obtuve {result.attempts}"
    assert calls["n"] == 3
    assert result.result == {"ok": True, "intentos": 3}


# --------------------------------------------------------------------------- #
# 4. EventLoop.run lanza TaskError y task.status="failed" cuando falla SIEMPRE
# --------------------------------------------------------------------------- #
def test_event_loop_run_always_fails_raises_taskerror():
    def handler(task: Task) -> Dict[str, Any]:
        raise RuntimeError("siempre falla")

    loop = EventLoop(
        supervisor=Supervisor(max_attempts=1),
        max_attempts=3,
        base_delay_s=0.001,
    )
    task = Task(goal="condenada")

    with pytest.raises(TaskError):
        asyncio.run(loop.run(task, handler))

    assert task.status == "failed"
    assert task.attempts == 3, f"esperaba 3 intentos, obtuve {task.attempts}"
    assert task.error is not None


# --------------------------------------------------------------------------- #
# 5. EventLoopCheckpointStore save/load round-trip
# --------------------------------------------------------------------------- #
def test_checkpoint_store_save_load_roundtrip():
    store, path = _make_store()
    try:
        cp = EventLoopCheckpointStore(store)
        task = Task(goal="checkpointed", payload={"x": 1})
        task.mark_succeeded({"ok": True})

        checkpoint_id = cp.save(
            run_id="r5",
            loop_state={"attempt": 1, "status": "succeeded"},
            task=task,
            tenant_id=None,
            session_id=None,
        )
        assert isinstance(checkpoint_id, str) and checkpoint_id

        loaded = cp.load(run_id="r5", tenant_id=None, session_id=None)
        assert loaded is not None
        assert loaded["run_id"] == "r5"
        assert loaded["task"]["goal"] == "checkpointed"
        assert loaded["task"]["status"] == "succeeded"
        assert loaded["task"]["result"] == {"ok": True}
        assert loaded["loop_state"]["status"] == "succeeded"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 6. EventLoop.resume tras reinicio: checkpoint en "running" continua y completa
# --------------------------------------------------------------------------- #
def test_event_loop_resume_after_crash_completes():
    store, path = _make_store()
    try:
        cp = EventLoopCheckpointStore(store)

        # Simulamos un crash: el loop se detuvo con la tarea en "running".
        task = Task(goal="reanudable")
        task.mark_running()
        cp.save(
            run_id="r6",
            loop_state={"attempt": 1, "status": "running"},
            task=task,
            tenant_id=None,
            session_id="s6",
        )

        def handler(task: Task) -> Dict[str, Any]:
            return {"recovered": True}

        # Nuevo EventLoop (reinicio) que rehidrata desde el checkpoint.
        loop = EventLoop(
            supervisor=Supervisor(max_attempts=1),
            checkpointer=cp,
            tenant_id=None,
            session_id="s6",
            max_attempts=3,
            base_delay_s=0.001,
        )
        recovered = asyncio.run(loop.resume(run_id="r6", handler=handler))
        assert recovered.status == "succeeded"
        assert recovered.goal == "reanudable"
        assert recovered.result == {"recovered": True}
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 7. EventLoop.resume con checkpoint ya "succeeded" es idempotente
# --------------------------------------------------------------------------- #
def test_event_loop_resume_idempotent_when_already_succeeded():
    store, path = _make_store()
    try:
        cp = EventLoopCheckpointStore(store)

        task = Task(goal="ya-hecha")
        task.mark_succeeded({"done": True})
        cp.save(
            run_id="r7",
            loop_state={"attempt": 1, "status": "succeeded"},
            task=task,
            tenant_id=None,
            session_id="s7",
        )

        def boom(task: Task) -> Dict[str, Any]:
            raise AssertionError("el handler NO debe ejecutarse en resume idempotente")

        loop = EventLoop(
            supervisor=Supervisor(max_attempts=1),
            checkpointer=cp,
            tenant_id=None,
            session_id="s7",
            max_attempts=3,
            base_delay_s=0.001,
        )
        result = asyncio.run(loop.resume(run_id="r7", handler=boom))
        assert result.status == "succeeded"
        assert result.result == {"done": True}
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 8. EventLoop.resume lanza EventLoopError si no hay checkpoint
# --------------------------------------------------------------------------- #
def test_event_loop_resume_without_checkpoint_raises():
    store, path = _make_store()
    try:
        cp = EventLoopCheckpointStore(store)
        loop = EventLoop(
            supervisor=Supervisor(max_attempts=1),
            checkpointer=cp,
            tenant_id=None,
            session_id="s8",
            max_attempts=3,
            base_delay_s=0.001,
        )

        def handler(task: Task) -> Dict[str, Any]:
            return {}

        with pytest.raises(EventLoopError):
            asyncio.run(loop.resume(run_id="run-inexistente", handler=handler))
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 9. AutonomousAgent.run_goal con plan=None ejecuta 1 tarea y devuelve lista de 1
# --------------------------------------------------------------------------- #
def test_autonomous_agent_run_goal_no_plan_single_task():
    def handler(task: Task) -> Dict[str, Any]:
        return {"goal": task.goal}

    agent = AutonomousAgent(
        supervisor=Supervisor(max_attempts=1),
        max_attempts=3,
    )
    tasks = asyncio.run(agent.run_goal("un solo objetivo", handler))

    assert isinstance(tasks, list)
    assert len(tasks) == 1, f"esperaba 1 tarea, obtuve {len(tasks)}"
    assert tasks[0].status == "succeeded"
    assert tasks[0].goal == "un solo objetivo"


# --------------------------------------------------------------------------- #
# 10. AutonomousAgent.run_goal con plan=["a","b","c"] ejecuta 3 tareas succeeded
# --------------------------------------------------------------------------- #
def test_autonomous_agent_run_goal_with_plan_runs_three_tasks():
    def handler(task: Task) -> Dict[str, Any]:
        return {"step": task.goal}

    agent = AutonomousAgent(
        supervisor=Supervisor(max_attempts=1),
        max_attempts=3,
    )
    tasks = asyncio.run(agent.run_goal("gran objetivo", handler, plan=["a", "b", "c"]))

    assert len(tasks) == 3, f"esperaba 3 tareas, obtuve {len(tasks)}"
    assert all(t.status == "succeeded" for t in tasks), "todas deben ser succeeded"
    assert [t.goal for t in tasks] == ["a", "b", "c"]


# --------------------------------------------------------------------------- #
# 11. AutonomousAgent integra SessionStore: session:<sid>:turns tiene N turnos
# --------------------------------------------------------------------------- #
def test_autonomous_agent_persists_session_turns():
    store, path = _make_store()
    try:
        session_store = SessionStore(store)

        def handler(task: Task) -> Dict[str, Any]:
            return {"ok": True}

        agent = AutonomousAgent(
            supervisor=Supervisor(max_attempts=1),
            session_store=session_store,
            tenant_id=None,
            session_id="s11",
            max_attempts=3,
        )
        plan = ["p1", "p2", "p3"]
        tasks = asyncio.run(agent.run_goal("objetivo", handler, plan=plan))
        assert len(tasks) == len(plan)

        # Verificamos directamente en el MemoryStore (clave session:<sid>:turns).
        blob = store.get(
            tenant_id=None, session_id="s11", key="session:s11:turns"
        )
        assert isinstance(blob, dict), "debe existir el blob de turnos"
        assert blob.get("version") == 1
        turns = blob.get("turns", [])
        assert len(turns) == len(plan), f"esperaba {len(plan)} turnos, obtuve {len(turns)}"
        assert [t["goal"] for t in turns] == plan
        assert all(t["status"] == "succeeded" for t in turns)
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 12. (bonus) Multitenancy: mismo run_id, distinto tenant => load aislado
# --------------------------------------------------------------------------- #
def test_checkpoint_store_multitenancy_isolation():
    store, path = _make_store()
    try:
        cp = EventLoopCheckpointStore(store)
        run_id = "shared-run"

        task_a = Task(goal="tarea-tenant-A")
        task_a.mark_succeeded({"tenant": "A"})
        task_b = Task(goal="tarea-tenant-B")
        task_b.mark_succeeded({"tenant": "B"})

        cp.save(
            run_id=run_id,
            loop_state={"attempt": 1, "status": "succeeded"},
            task=task_a,
            tenant_id="tenantA",
            session_id=None,
        )
        cp.save(
            run_id=run_id,
            loop_state={"attempt": 1, "status": "succeeded"},
            task=task_b,
            tenant_id="tenantB",
            session_id=None,
        )

        loaded_a = cp.load(run_id=run_id, tenant_id="tenantA", session_id=None)
        loaded_b = cp.load(run_id=run_id, tenant_id="tenantB", session_id=None)

        assert loaded_a is not None and loaded_b is not None
        assert loaded_a["task"]["goal"] == "tarea-tenant-A"
        assert loaded_b["task"]["goal"] == "tarea-tenant-B"
        assert loaded_a["task"]["result"] == {"tenant": "A"}
        assert loaded_b["task"]["result"] == {"tenant": "B"}

        # El tenant opuesto NO debe ver el otro checkpoint.
        assert loaded_a["task"]["goal"] != loaded_b["task"]["goal"]
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass
