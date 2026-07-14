from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ciel.orchestration.session import SessionStore
from ciel.orchestration.supervisor import Supervisor, WorkerContext
from ciel.runtime.memory import MemoryStore


# Fase 5 — root_agent con sub_agents estilo ADK (Google Agent Development Kit).
#
# Un ``RootAgent`` coordina y enruta una petición a specialist agents. La
# jerarquía es nativa (root -> specialists), no monolítica. El enrutamiento es
# modelo-agnóstico: un ``router`` recibe el texto de la petición y devuelve el
# ``name`` del specialist que debe atenderla (o ``None`` para manejarla en root).
#
# Cada specialist es una función ``handler(state) -> resultado`` ejecutada a
# través del ``Supervisor`` existente (hereda retry/timeout/budget/rate-limit
# por worker), igual que el grafo y los flows. Esto es OFFLINE-SAFE: demos/cli
# usan routers y handlers locales sobre ``state_data``, pero un specialist real
# puede invocar ``ciel.runtime`` (provider/modelo).

RoutingFn = Callable[[str], Any]  # recibe el prompt -> nombre del specialist o None
HandlerFn = Callable[["RootState"], Any]


@dataclass
class RootState:
    """Estado compartido del root agent: prompt, ruta elegida y resultado.

    ``history`` acumula los turnos previos de la session (estilo ADK session
    state) para que el agente recuerde contexto entre invocaciones.
    """

    prompt: str = ""
    route: Optional[str] = None
    result: Any = None
    handled_by_root: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "route": self.route,
            "result": self.result,
            "handled_by_root": self.handled_by_root,
            "metadata": dict(self.metadata),
            "history": [dict(h) for h in self.history],
        }

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any]) -> "RootState":
        return cls(
            prompt=snap.get("prompt", ""),
            route=snap.get("route"),
            result=snap.get("result"),
            handled_by_root=bool(snap.get("handled_by_root", False)),
            metadata=dict(snap.get("metadata", {})),
            history=[dict(h) for h in snap.get("history", [])],
        )


class RootAgentError(Exception):
    pass


@dataclass
class Specialist:
    """Agente especialista enrutado por el root agent (ADK sub_agent)."""

    name: str
    handler: HandlerFn
    description: str = ""

    async def _handle(self, state: RootState) -> Any:
        res = self.handler(state)
        if hasattr(res, "__await__"):
            return await res
        return res


class RootAgent:
    """Builder declarativo: ``add_specialist`` + ``set_router``; luego ``compile``.

    El ``router`` decide a qué specialist enrutar la petición. Si devuelve
    ``None``, el ``root_handler`` (opcional) la atiende localmente.
    """

    def __init__(self, name: str = "root") -> None:
        self.name = name
        self._specialists: Dict[str, Specialist] = {}
        self._router: Optional[RoutingFn] = None
        self._root_handler: Optional[HandlerFn] = None

    def add_specialist(self, specialist: Specialist) -> "RootAgent":
        if specialist.name in self._specialists:
            raise RootAgentError(f"specialist '{specialist.name}' already registered")
        self._specialists[specialist.name] = specialist
        return self

    def set_router(self, router: RoutingFn) -> "RootAgent":
        self._router = router
        return self

    def set_root_handler(self, handler: HandlerFn) -> "RootAgent":
        self._root_handler = handler
        return self

    def specialists(self) -> Dict[str, Specialist]:
        return dict(self._specialists)

    def compile(
        self,
        *,
        supervisor: Optional[Supervisor] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "RootRunner":
        if self._router is None and self._root_handler is None:
            raise RootAgentError("root agent needs a router and/or a root_handler")
        return RootRunner(
            agent=self,
            supervisor=supervisor or Supervisor(),
            tenant_id=tenant_id,
            session_id=session_id,
        )


class RootRunner:
    """Ejecuta el root agent: enruta la petición y ejecuta el specialist (o root)."""

    def __init__(
        self,
        *,
        agent: RootAgent,
        supervisor: Supervisor,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_store: Optional[SessionStore] = None,
    ) -> None:
        self.agent = agent
        self.supervisor = supervisor
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.session_store = session_store or (SessionStore(supervisor._memory) if hasattr(supervisor, "_memory") else None)

    async def _run_worker(self, worker_id: str, fn: Callable[["RootState"], Any], state: RootState) -> Any:
        async def _worker(ctx: WorkerContext) -> Any:
            return await self._invoke(fn, state)

        result = await self.supervisor.run(
            step_id=f"root:{worker_id}",
            worker=_worker,
            payload={"worker": worker_id},
            worker_id=worker_id,
        )
        if result.failed:
            raise RootAgentError(f"worker '{worker_id}' failed after {result.attempts} attempts: {result.error}")
        return result.output

    @staticmethod
    async def _invoke(fn: Callable[["RootState"], Any], state: RootState) -> Any:
        res = fn(state)
        if hasattr(res, "__await__"):
            return await res
        return res

    async def route(
        self,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        session_store: Optional[SessionStore] = None,
        tenant_id: Optional[str] = None,
    ) -> RootState:
        """Enruta y ejecuta la petición, manteniendo session state por tenant.

        Si se pasa ``session_id`` (+ ``session_store``/``tenant_id``), el estado
        del agente se reconstruye con el historial de turnos previos y el turno
        resultante se persiste para la próxima invocación (estilo ADK session
        state entre turnos). OFFLINE-SAFE: no requiere red ni proveedor.
        """
        sid = session_id if session_id is not None else self.session_id
        store = session_store if session_store is not None else self.session_store
        tid = tenant_id if tenant_id is not None else self.tenant_id

        # Rehidrata el historial de turnos previos de la session (si existe).
        prior_history: List[Dict[str, Any]] = []
        if store is not None and sid is not None:
            prior_history = store.history(tenant_id=tid, session_id=sid)

        state = RootState(prompt=prompt, history=list(prior_history))
        router = self.agent._router
        if router is not None:
            target = router(prompt)
            if isinstance(target, Awaitable):
                target = await target
            if target is not None:
                if target not in self.agent._specialists:
                    raise RootAgentError(f"router returned unknown specialist '{target}'")
                state.route = target
                state.result = await self._run_worker(target, self.agent._specialists[target]._handle, state)
                state.metadata["handled_by"] = target
                self._persist_turn(store, tid, sid, state)
                return state
        # Sin enrutamiento -> lo maneja el root (si lo hay).
        if self.agent._root_handler is not None:
            state.handled_by_root = True
            state.result = await self._run_worker("root", self.agent._root_handler, state)
            state.metadata["handled_by"] = self.agent.name
            self._persist_turn(store, tid, sid, state)
            return state
        raise RootAgentError("router returned None and no root_handler is configured")

    @staticmethod
    def _persist_turn(
        store: Optional[SessionStore],
        tid: Optional[str],
        sid: Optional[str],
        state: RootState,
    ) -> None:
        """Persiste el turno en la session si hay session store + id."""
        if store is None or sid is None:
            return
        turn = {
            "prompt": state.prompt,
            "route": state.route,
            "result": state.result,
            "handled_by_root": state.handled_by_root,
            "handled_by": state.metadata.get("handled_by"),
        }
        store.append_turn(tenant_id=tid, session_id=sid, turn=turn)


class RootCheckpointStore:
    """Persistencia de la decisión de enrutamiento sobre ``MemoryStore``."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def _key(self, run_id: str) -> str:
        return f"root:{run_id}"

    def save(self, *, run_id: str, state: RootState, tenant_id: Optional[str], session_id: Optional[str]) -> str:
        import uuid

        checkpoint_id = str(uuid.uuid4())
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id or run_id,
            key=self._key(run_id),
            value={"checkpoint_id": checkpoint_id, "run_id": run_id, "state": state.snapshot()},
        )
        return checkpoint_id

    def load(self, *, run_id: str, tenant_id: Optional[str], session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        payload = self.memory.get(tenant_id=tenant_id, session_id=session_id or run_id, key=self._key(run_id))
        return payload if isinstance(payload, dict) else None
