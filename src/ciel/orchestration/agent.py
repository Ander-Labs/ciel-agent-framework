from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from ciel.orchestration.session import SessionStore
from ciel.orchestration.supervisor import Supervisor, WorkerContext
from ciel.runtime.memory import MemoryStore


# Fase 6 — Agencia autónoma en bucle (AutoGen/ADK).
#
# ``EventLoop`` ejecuta una ``Task`` autónoma sobre el ``Supervisor`` existente
# (hereda retry/timeout/budget) con reintentos exponenciales y checkpoint
# durable sobre ``MemoryStore`` (multitenancy nativo). Tras un reinicio,
# ``EventLoop.resume`` rehidrata el estado desde el checkpoint y continúa,
# completando la tarea (criterio de avance de Fase 6).
#
# La cola de larga duración ``DurableQueue`` (SQLite WAL, en ``queue.py``) se
# reutiliza como backing store del loop cuando se enlaza una ``Task`` con un
# ``run_id``/``tenant_id``.
#
# ``AutonomousAgent`` es el orquestador de nivel superior: recibe un objetivo,
# lo descompone en una lista de ``Task`` (offline-safe, handlers locales sobre
# ``task.payload``) y las ejecuta/ejecuta en bucle vía ``EventLoop``,
# persistiendo su session state con ``SessionStore`` (ADK session_state).
#
# OFFLINE-SAFE: los demos/CLI usan handlers locales y echo provider; no se
# requiere red ni proveedor real.

# ---------------------------------------------------------------------------
# Tipos de handler
# ---------------------------------------------------------------------------
# Un handler recibe un ``Task`` mutable y devuelve un resultado (valor o
# corutina). Puede fallar (raise) para forzar reintento exponencial.
TaskHandler = Callable[["Task"], Any]


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------
class AgentError(Exception):
    """Error base de la agencia autónoma (Fase 6)."""


class EventLoopError(AgentError):
    """Error del bucle de eventos (reintentos agotados, estado inválido)."""


class TaskError(AgentError):
    """Error de una tarea individual tras agotar reintentos."""


# ---------------------------------------------------------------------------
# Modelo de tarea
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """Unidad de trabajo autónomo durable (estilo ADK/AutoGen task).

    ``status``: ``pending`` | ``running`` | ``succeeded`` | ``failed``.
    ``attempts`` se incrementa por cada ejecución del handler.
    """

    goal: str
    payload: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    attempts: int = 0
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "payload": dict(self.payload),
            "status": self.status,
            "attempts": self.attempts,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any]) -> "Task":
        return cls(
            id=snap.get("id", str(uuid.uuid4())),
            goal=snap.get("goal", ""),
            payload=dict(snap.get("payload", {})),
            status=snap.get("status", "pending"),
            attempts=snap.get("attempts", 0),
            result=snap.get("result"),
            error=snap.get("error"),
            created_at=snap.get("created_at", time.time()),
            updated_at=snap.get("updated_at", time.time()),
        )

    def mark_running(self) -> None:
        self.status = "running"
        self.updated_at = time.time()

    def mark_succeeded(self, result: Any) -> None:
        self.status = "succeeded"
        self.result = result
        self.error = None
        self.updated_at = time.time()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.updated_at = time.time()


# ---------------------------------------------------------------------------
# Checkpoint store (sobre MemoryStore, multitenancy nativo)
# ---------------------------------------------------------------------------
class EventLoopCheckpointStore:
    """Persiste el estado del EventLoop sobre ``MemoryStore``.

    Clave: ``loop:<run_id>`` (namespaced para no colisionar con otros módulos).
    Guarda el ``Task`` en curso + el estado del loop (intent, estado global).
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def _key(self, run_id: str) -> str:
        return f"loop:{run_id}"

    def save(
        self,
        *,
        run_id: str,
        loop_state: Dict[str, Any],
        task: Task,
        tenant_id: Optional[str],
        session_id: Optional[str],
    ) -> str:
        checkpoint_id = str(uuid.uuid4())
        payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "loop_state": dict(loop_state),
            "task": task.snapshot(),
        }
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id or run_id,
            key=self._key(run_id),
            value=payload,
        )
        return checkpoint_id

    def load(
        self, *, run_id: str, tenant_id: Optional[str], session_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        payload = self.memory.get(
            tenant_id=tenant_id, session_id=session_id or run_id, key=self._key(run_id)
        )
        return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# EventLoop — bucle durable con reintentos exponenciales
# ---------------------------------------------------------------------------
@dataclass
class EventLoopStep:
    """Resultado de un intento de ejecución de una tarea en el loop."""

    attempt: int
    succeeded: bool
    output: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0


class EventLoop:
    """Bucle de eventos durable que ejecuta una ``Task`` con reintentos.

    Montado sobre ``Supervisor`` (retry/timeout/budget por worker). Si el
    handler falla, el loop aplica backoff exponencial (capped) y reintenta
    hasta ``max_attempts``. Tras cada intento persiste un checkpoint en
    ``MemoryStore``; ``resume`` rehidrata y continúa.

    OFFLINE-SAFE: el handler por defecto (y los demos) son funciones locales.
    """

    def __init__(
        self,
        *,
        supervisor: Optional[Supervisor] = None,
        checkpointer: Optional[EventLoopCheckpointStore] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_attempts: int = 5,
        base_delay_s: float = 0.05,
        max_delay_s: float = 2.0,
        jitter: bool = False,
    ) -> None:
        self.supervisor = supervisor or Supervisor()
        self.checkpointer = checkpointer
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.max_attempts = max_attempts
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        self.jitter = jitter
        self.run_id: Optional[str] = None
        self.task: Optional[Task] = None
        self.steps: List[EventLoopStep] = []

    # -- helpers -------------------------------------------------------------
    @staticmethod
    async def _invoke(fn: TaskHandler, task: Task) -> Any:
        res = fn(task)
        if hasattr(res, "__await__"):
            return await res
        return res

    def _backoff(self, attempt: int) -> float:
        delay = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        if self.jitter:
            delay += (time.perf_counter() % 1) * 0.01
        return delay

    def _save(self, loop_state: Dict[str, Any]) -> None:
        if self.checkpointer is not None and self.run_id is not None and self.task is not None:
            self.checkpointer.save(
                run_id=self.run_id,
                loop_state=loop_state,
                task=self.task,
                tenant_id=self.tenant_id,
                session_id=self.session_id,
            )

    # -- run -----------------------------------------------------------------
    async def run(
        self,
        task: Task,
        handler: TaskHandler,
        *,
        run_id: Optional[str] = None,
    ) -> Task:
        """Ejecuta ``task`` con reintentos exponenciales hasta completar o agotar."""
        self.run_id = run_id or str(uuid.uuid4())
        self.task = task
        self.steps = []

        attempt = 0
        last_error: Optional[str] = None
        while attempt < self.max_attempts:
            attempt += 1
            task.attempts = attempt
            task.mark_running()
            start = time.perf_counter()
            try:
                result = await self.supervisor.run(
                    step_id=f"{self.run_id}:attempt:{attempt}",
                    worker=self._make_worker(handler, task),
                    payload={"attempt": attempt},
                    worker_id=f"loop-{attempt}",
                )
                latency = (time.perf_counter() - start) * 1000.0
                if result.failed:
                    # El Supervisor ya agotó sus reintentos internos.
                    last_error = result.error or "supervisor worker failed"
                    self.steps.append(
                        EventLoopStep(attempt=attempt, succeeded=False, error=last_error, latency_ms=latency)
                    )
                else:
                    task.mark_succeeded(result.output)
                    self.steps.append(
                        EventLoopStep(attempt=attempt, succeeded=True, output=result.output, latency_ms=latency)
                    )
                    self._save({"attempt": attempt, "status": task.status})
                    return task
            except Exception as exc:  # handler levantó fuera del supervisor
                last_error = str(exc)
                latency = (time.perf_counter() - start) * 1000.0
                self.steps.append(
                    EventLoopStep(attempt=attempt, succeeded=False, error=last_error, latency_ms=latency)
                )

            self._save({"attempt": attempt, "status": task.status})
            if attempt < self.max_attempts:
                await asyncio.sleep(self._backoff(attempt))

        task.mark_failed(last_error or "unknown failure")
        self._save({"attempt": attempt, "status": task.status})
        raise TaskError(
            f"task '{task.goal}' failed after {attempt} attempts: {task.error}"
        )

    def _make_worker(self, handler: TaskHandler, task: Task):
        async def _worker(ctx: WorkerContext) -> Any:
            return await self._invoke(handler, task)

        return _worker

    # -- resume --------------------------------------------------------------
    async def resume(self, *, run_id: str, handler: TaskHandler) -> Task:
        """Reanuda un loop interrumpido desde su último checkpoint.

        Rehidrata la ``Task`` persistida y continúa los reintentos. Si la tarea
        ya estaba en ``succeeded``/``failed`` al interrumpirse, la devuelve tal
        cual (idempotente). Cumple el criterio Fase 6: tras reinicio continúa y
        completa.
        """
        if self.checkpointer is None:
            raise EventLoopError("resume requires a checkpointer")
        self.run_id = run_id
        payload = self.checkpointer.load(
            run_id=run_id, tenant_id=self.tenant_id, session_id=self.session_id
        )
        if payload is None:
            raise EventLoopError(f"no checkpoint found for run_id '{run_id}'")
        task = Task.from_snapshot(payload["task"])
        self.task = task
        loop_state = payload.get("loop_state", {})
        self.steps = []

        # Si ya terminó en el checkpoint previo, no re-ejecutar.
        if task.status in ("succeeded", "failed"):
            return task

        attempt = int(loop_state.get("attempt", 0))
        last_error: Optional[str] = None
        while attempt < self.max_attempts:
            attempt += 1
            task.attempts = attempt
            task.mark_running()
            start = time.perf_counter()
            try:
                result = await self.supervisor.run(
                    step_id=f"{self.run_id}:attempt:{attempt}",
                    worker=self._make_worker(handler, task),
                    payload={"attempt": attempt},
                    worker_id=f"loop-{attempt}",
                )
                latency = (time.perf_counter() - start) * 1000.0
                if result.failed:
                    last_error = result.error or "supervisor worker failed"
                    self.steps.append(
                        EventLoopStep(attempt=attempt, succeeded=False, error=last_error, latency_ms=latency)
                    )
                else:
                    task.mark_succeeded(result.output)
                    self.steps.append(
                        EventLoopStep(attempt=attempt, succeeded=True, output=result.output, latency_ms=latency)
                    )
                    self._save({"attempt": attempt, "status": task.status})
                    return task
            except Exception as exc:
                last_error = str(exc)
                latency = (time.perf_counter() - start) * 1000.0
                self.steps.append(
                    EventLoopStep(attempt=attempt, succeeded=False, error=last_error, latency_ms=latency)
                )

            self._save({"attempt": attempt, "status": task.status})
            if attempt < self.max_attempts:
                await asyncio.sleep(self._backoff(attempt))

        task.mark_failed(last_error or "unknown failure")
        self._save({"attempt": attempt, "status": task.status})
        raise TaskError(
            f"task '{task.goal}' failed after resume ({attempt} attempts): {task.error}"
        )


# ---------------------------------------------------------------------------
# AutonomousAgent — orquestador de nivel superior
# ---------------------------------------------------------------------------
class AutonomousAgent:
    """Agente autónomo que descompone un objetivo en tareas y las ejecuta.

    OFFLINE-SAFE: por defecto el planner es un handler local que parte el
    objetivo en una sola tarea (o N tareas si se provee ``plan`` explícito);
    cada tarea se ejecuta con un handler local sobre ``task.payload`` (no red).
    """

    def __init__(
        self,
        name: str = "autonomous",
        *,
        supervisor: Optional[Supervisor] = None,
        checkpointer: Optional[EventLoopCheckpointStore] = None,
        session_store: Optional[SessionStore] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_attempts: int = 5,
    ) -> None:
        self.name = name
        self.supervisor = supervisor or Supervisor()
        self.checkpointer = checkpointer
        self.session_store = session_store
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.max_attempts = max_attempts

    def _loop(self, task: Task, handler: TaskHandler) -> EventLoop:
        return EventLoop(
            supervisor=self.supervisor,
            checkpointer=self.checkpointer,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            max_attempts=self.max_attempts,
        )

    async def run_task(self, task: Task, handler: TaskHandler) -> Task:
        loop = self._loop(task, handler)
        return await loop.run(task, handler)

    async def run_goal(
        self,
        goal: str,
        handler: TaskHandler,
        *,
        plan: Optional[Sequence[str]] = None,
    ) -> List[Task]:
        """Descompone ``goal`` en tareas (``plan`` o una sola) y las ejecuta.

        Cada tarea completada persiste un turno en ``SessionStore`` si está
        disponible (ADK session_state entre ejecuciones del agente).
        """
        steps = list(plan) if plan else [goal]
        tasks: List[Task] = [Task(goal=step) for step in steps]
        for task in tasks:
            await self.run_task(task, handler)
            self._persist_turn(task)
        return tasks

    def _persist_turn(self, task: Task) -> None:
        if self.session_store is None or self.session_id is None:
            return
        self.session_store.append_turn(
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            turn={
                "goal": task.goal,
                "status": task.status,
                "result": task.result,
                "attempts": task.attempts,
            },
        )


__all__ = [
    "AgentError",
    "EventLoopError",
    "TaskError",
    "Task",
    "EventLoopCheckpointStore",
    "EventLoop",
    "EventLoopStep",
    "AutonomousAgent",
]
