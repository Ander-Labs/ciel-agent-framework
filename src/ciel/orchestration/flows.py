from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from ciel.orchestration.supervisor import Supervisor, Worker, WorkerContext
from ciel.runtime.memory import MemoryStore


# Fase 5 — Flows event-driven estilo CrewAI.Flows.
#
# Un ``Flow`` es un grafo de EVENTOS dirigido (DAG) de pasos. Cada paso es una
# función que recibe el ``FlowState`` mutable y devuelve un resultado:
#
#   - ``start``     : no tiene dependencias, se ejecuta al inicio.
#   - ``listen(src)``: se dispara cuando el paso ``src`` termina (evento).
#   - ``router(src, branches)``: como ``listen``, pero tras ejecutarse activa
#     EXACTAMENTE una rama ``branches[resultado]`` (enruta a un paso concreto).
#
# El estado se comparte en ``FlowState.data`` (como ``self.state`` de CrewAI) y
# se persiste tras cada paso para ``resume`` de flujos long-running. Se monta
# SOBRE ``Supervisor`` existente: cada paso hereda retry/timeout/budget/rate-limit.

StepFn = Callable[["FlowState"], Any]
SyncOrAsync = Any  # StepFn puede devolver un valor o una corutina


@dataclass
class FlowState:
    """Estado mutable compartido entre pasos de un flow (estilo CrewAI state)."""

    data: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    completed: List[str] = field(default_factory=list)
    last_event: Optional[str] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "data": dict(self.data),
            "results": dict(self.results),
            "completed": list(self.completed),
            "last_event": self.last_event,
        }

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any]) -> "FlowState":
        return cls(
            data=dict(snap.get("data", {})),
            results=dict(snap.get("results", {})),
            completed=list(snap.get("completed", [])),
            last_event=snap.get("last_event"),
        )


@dataclass
class FlowStep:
    id: str
    kind: str  # "start" | "listen" | "router"
    fn: StepFn
    source: Optional[str] = None
    branches: Dict[Any, str] = field(default_factory=dict)  # router: valor -> paso destino


class FlowError(Exception):
    pass


class Flow:
    """Constructor declarativo de flows event-driven.

    API: ``add_start``, ``add_listen``, ``add_router``; luego ``compile``.
    Los IDs de paso se derivan del ``__name__`` de la función salvo que se
    pasen explícitamente.
    """

    def __init__(self, name: str = "flow") -> None:
        self.name = name
        self._steps: Dict[str, FlowStep] = {}
        self._order: List[str] = []
        self._sources: Dict[str, set] = {}  # paso -> conjunto de pasos fuente
        self._router_branches: Dict[str, Dict[Any, str]] = {}  # router -> {valor: destino}

    # -- registro ------------------------------------------------------------
    def add_start(self, fn: StepFn, step_id: Optional[str] = None) -> "Flow":
        sid = step_id or getattr(fn, "__name__", "start")
        self._register(FlowStep(id=sid, kind="start", fn=fn))
        self._sources[sid] = set()
        return self

    def add_listen(self, source_id: str, fn: StepFn, step_id: Optional[str] = None) -> "Flow":
        sid = step_id or getattr(fn, "__name__", "listen")
        self._register(FlowStep(id=sid, kind="listen", fn=fn, source=source_id))
        self._sources[sid] = {source_id}
        return self

    def add_router(
        self,
        source_id: str,
        fn: StepFn,
        branches: Dict[Any, str],
        step_id: Optional[str] = None,
    ) -> "Flow":
        sid = step_id or getattr(fn, "__name__", "router")
        self._register(FlowStep(id=sid, kind="router", fn=fn, source=source_id, branches=dict(branches)))
        self._sources[sid] = {source_id}
        self._router_branches[sid] = dict(branches)
        return self

    def add_branch(self, fn: StepFn, step_id: Optional[str] = None) -> "Flow":
        """Paso rama activado EXCLUSIVAMENTE por un router (no tiene fuente de datos)."""
        sid = step_id or getattr(fn, "__name__", "branch")
        self._register(FlowStep(id=sid, kind="branch", fn=fn))
        self._sources[sid] = set()
        return self

    def _register(self, step: FlowStep) -> None:
        if step.id in self._steps:
            raise FlowError(f"step '{step.id}' already registered")
        self._steps[step.id] = step
        self._order.append(step.id)

    def steps(self) -> Dict[str, FlowStep]:
        return dict(self._steps)

    def compile(
        self,
        *,
        supervisor: Optional[Supervisor] = None,
        max_steps: int = 256,
        checkpointer: Optional["FlowCheckpointStore"] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "FlowRunner":
        # Validación de que los destinos de router existen (evita carreras en runtime).
        for rid, branches in self._router_branches.items():
            for tid in branches.values():
                if tid not in self._steps:
                    raise FlowError(f"router '{rid}' branch target '{tid}' is not registered")
        return FlowRunner(
            flow=self,
            supervisor=supervisor or Supervisor(),
            max_steps=max_steps,
            checkpointer=checkpointer,
            tenant_id=tenant_id,
            session_id=session_id,
        )


class FlowCheckpointStore:
    """Persistencia de checkpoints de flow sobre ``MemoryStore`` (multitenancy nativo)."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def _key(self, run_id: str) -> str:
        return f"flow:{run_id}"

    def save(
        self,
        *,
        run_id: str,
        completed: Sequence[str],
        state: FlowState,
        finished: bool,
        tenant_id: Optional[str],
        session_id: Optional[str],
    ) -> str:
        checkpoint_id = str(uuid.uuid4())
        payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "completed": list(completed),
            "finished": finished,
            "state": state.snapshot(),
        }
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id or run_id,
            key=self._key(run_id),
            value=payload,
        )
        return checkpoint_id

    def load(self, *, run_id: str, tenant_id: Optional[str], session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        payload = self.memory.get(tenant_id=tenant_id, session_id=session_id or run_id, key=self._key(run_id))
        return payload if isinstance(payload, dict) else None


class FlowRunner:
    """Ejecuta el flow paso a paso (event-driven) con checkpoint + resume."""

    def __init__(
        self,
        *,
        flow: Flow,
        supervisor: Supervisor,
        max_steps: int = 256,
        checkpointer: Optional[FlowCheckpointStore] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.flow = flow
        self.supervisor = supervisor
        self.max_steps = max_steps
        self.checkpointer = checkpointer
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.run_id: Optional[str] = None
        self._activated: set = set()

    async def _run_step(self, step: FlowStep, state: FlowState, idx: int) -> Any:
        async def _worker(ctx: WorkerContext) -> Any:
            res = step.fn(state)
            if hasattr(res, "__await__"):
                return await res
            return res

        result = await self.supervisor.run(
            step_id=f"{self.run_id}:{step.id}:{idx}",
            worker=_worker,
            payload={"step": step.id, "kind": step.kind},
            worker_id=step.id,
        )
        if result.failed:
            raise FlowError(f"step '{step.id}' failed after {result.attempts} attempts: {result.error}")
        return result.output

    def _ready(self, state: FlowState) -> List[str]:
        out: List[str] = []
        for sid in self.flow._order:
            if sid in state.completed:
                continue
            step = self.flow._steps[sid]
            # Una rama SOLO está lista si un router la activó explícitamente.
            if step.kind == "branch":
                if sid in self._activated:
                    out.append(sid)
                continue
            if sid in self._activated:
                out.append(sid)
                continue
            srcs = self.flow._sources.get(sid, set())
            if all(s in state.completed for s in srcs):
                out.append(sid)
        return out

    async def _drive(self, state: FlowState) -> FlowState:
        idx = 0
        while True:
            ready = self._ready(state)
            if not ready:
                break
            sid = ready[0]  # determinista: orden de registro
            step = self.flow._steps[sid]
            out = await self._run_step(step, state, idx)
            state.results[sid] = out
            state.data.setdefault("__out__", {})[sid] = out
            state.completed.append(sid)
            state.last_event = sid
            idx += 1

            # Un router activa exactamente una rama tras completarse.
            if step.kind == "router":
                target = self.flow._router_branches[sid].get(out)
                if target is None:
                    raise FlowError(f"router '{sid}' returned {out!r} with no matching branch")
                self._activated.add(target)

            if self.checkpointer is not None:
                self.checkpointer.save(
                    run_id=self.run_id,
                    completed=state.completed,
                    state=state,
                    finished=False,
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                )
            if idx >= self.max_steps:
                raise FlowError(f"exceeded max_steps={self.max_steps} (possible cycle)")
        state.last_event = state.completed[-1] if state.completed else None
        return state

    async def run(self, *, initial_data: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> FlowState:
        self.run_id = run_id or str(uuid.uuid4())
        self._activated = set()
        state = FlowState(data=dict(initial_data or {}))
        return await self._drive(state)

    async def resume(self, *, run_id: str) -> FlowState:
        """Reanuda un flow interrumpido desde su último checkpoint.

        Reconstruye el estado persistido y recomputa las ramas de router ya
        activadas (derivables de los routers completados + sus resultados).
        """
        if self.checkpointer is None:
            raise FlowError("resume requires a checkpointer")
        self.run_id = run_id
        payload = self.checkpointer.load(run_id=run_id, tenant_id=self.tenant_id, session_id=self.session_id)
        if payload is None:
            raise FlowError(f"no checkpoint found for run_id '{run_id}'")
        state = FlowState.from_snapshot(payload["state"])
        self._activated = set()
        for rid, branches in self.flow._router_branches.items():
            if rid in state.completed:
                target = branches.get(state.results.get(rid))
                if target:
                    self._activated.add(target)
        return await self._drive(state)


# Cierre de lint: Worker importado por si se extiende el patrón de swarm/cli.
_ = Worker
