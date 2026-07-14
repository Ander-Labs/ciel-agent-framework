from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from ciel.orchestration.supervisor import Supervisor, Worker, WorkerContext, WorkerResult
from ciel.runtime.memory import MemoryStore


# Nodo del grafo: una unidad de ejecución que recibe el estado y devuelve un
# payload. Se ejecuta a través del Supervisor existente, heredando
# retry/timeout/budget/rate-limit por nodo (estilo LangGraph, pero con el
# gobierno enterprise que ya tiene ciel).
NodeFn = Callable[[Dict[str, Any]], Awaitable[Any]]


class GraphError(Exception):
    pass


class GraphApprovalDenied(Exception):
    """Lanzada cuando un nodo pausado por HIL es denegado por el aprobadador."""


class GraphPaused(Exception):
    """Lanzada por ``run`` cuando un nodo exige aprobación (HIL).

    Atributos:
        node_id: id del nodo pausado.
        action: acción RBAC requerida para aprobar (p. ej. ``"approve:deploy"``).
        run_id: id del run pausado (para reanudar con ``approve``).
    """

    def __init__(self, message: str, *, node_id: str, action: str, run_id: str) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.action = action
        self.run_id = run_id


@dataclass
class GraphNode:
    id: str
    fn: NodeFn
    worker_id: str = "node"
    supervisor_kwargs: Dict[str, Any] = field(default_factory=dict)
    # Human-in-the-loop: si se define, el runner pausa ANTES de ejecutar el
    # nodo y exige aprobación RBAC con esta acción (p. ej. "approve:deploy").
    require_approval: Optional[str] = None


# Aristas: control de flujo explícito. `condition` opcional decide a qué
# nodo(s) seguir en función del estado tras ejecutar el nodo origen. Si no hay
# aristas salientes, el nodo es terminal.
EdgeCondition = Callable[[Dict[str, Any]], bool]


@dataclass
class GraphEdge:
    source: str
    target: str
    condition: Optional[EdgeCondition] = None


@dataclass
class GraphState:
    """Estado mutable compartido entre nodos (estilo state machine LangGraph)."""

    data: Dict[str, Any] = field(default_factory=dict)
    visited: List[str] = field(default_factory=list)
    current_node: Optional[str] = None
    last_output: Any = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "data": dict(self.data),
            "visited": list(self.visited),
            "current_node": self.current_node,
            "last_output": self.last_output,
        }

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any]) -> GraphState:
        return cls(
            data=dict(snap.get("data", {})),
            visited=list(snap.get("visited", [])),
            current_node=snap.get("current_node"),
            last_output=snap.get("last_output"),
        )


class GraphError(Exception):
    pass


class StateGraph:
    """Grafo de estado explícito, cíclico/condicional, con checkpoint.

    - ``add_node`` registra un nodo ejecutable.
    - ``add_edge`` registra una transición incondicional.
    - ``add_conditional_edges`` registra transiciones con guarda booleana.
    - ``set_entry_point`` / ``set_finish_point`` definen inicio y fin.
    """

    def __init__(self, name: str = "graph") -> None:
        self.name = name
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._entry: Optional[str] = None
        self._finish: Optional[str] = None

    def add_node(
        self,
        node_id: str,
        fn: NodeFn,
        *,
        worker_id: str = "node",
        supervisor_kwargs: Optional[Dict[str, Any]] = None,
        require_approval: Optional[str] = None,
    ) -> "StateGraph":
        if node_id in self._nodes:
            raise GraphError(f"node '{node_id}' already exists")
        self._nodes[node_id] = GraphNode(
            id=node_id,
            fn=fn,
            worker_id=worker_id,
            supervisor_kwargs=supervisor_kwargs or {},
            require_approval=require_approval,
        )
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        self._require_node(source)
        self._require_node(target)
        self._edges.append(GraphEdge(source=source, target=target))
        return self

    def add_conditional_edges(
        self,
        source: str,
        targets: Sequence[str],
        condition: EdgeCondition,
    ) -> "StateGraph":
        self._require_node(source)
        for t in targets:
            self._require_node(t)
            self._edges.append(GraphEdge(source=source, target=t, condition=condition))
        return self

    def set_entry_point(self, node_id: str) -> "StateGraph":
        self._require_node(node_id)
        self._entry = node_id
        return self

    def set_finish_point(self, node_id: str) -> "StateGraph":
        self._require_node(node_id)
        self._finish = node_id
        return self

    @property
    def nodes(self) -> Dict[str, GraphNode]:
        return dict(self._nodes)

    def outgoing(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self._edges if e.source == node_id]

    def _require_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise GraphError(f"unknown node '{node_id}'")

    def compile(
        self,
        *,
        supervisor: Optional[Supervisor] = None,
        max_steps: int = 64,
        checkpointer: Optional["GraphCheckpointStore"] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "GraphRunner":
        if self._entry is None:
            raise GraphError("entry point not set; call set_entry_point(...)")
        return GraphRunner(
            graph=self,
            supervisor=supervisor or Supervisor(),
            max_steps=max_steps,
            checkpointer=checkpointer,
            tenant_id=tenant_id,
            session_id=session_id,
        )


class GraphCheckpointStore:
    """Persistencia de checkpoints del grafo sobre ``MemoryStore``.

    Mismo patrón que ``ciel.runtime.checkpoints.CheckpointStore``: usa la
    clave ``(tenant_id, session_id, key)`` ya con multitenancy nativo.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def _key(self, run_id: str) -> str:
        return f"graph:{run_id}"

    def save(self, *, run_id: str, step_index: int, state: GraphState, finished: bool, tenant_id: Optional[str], session_id: Optional[str], paused: bool = False, paused_node: Optional[str] = None) -> str:
        checkpoint_id = str(uuid.uuid4())
        payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "step_index": step_index,
            "finished": finished,
            "paused": paused,
            "paused_node": paused_node,
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
        payload = self.memory.get(
            tenant_id=tenant_id,
            session_id=session_id or run_id,
            key=self._key(run_id),
        )
        return payload if isinstance(payload, dict) else None


class GraphRunner:
    """Ejecuta el grafo nodo a nodo, con checkpoint + reanudación + time-travel."""

    def __init__(
        self,
        *,
        graph: StateGraph,
        supervisor: Supervisor,
        max_steps: int = 64,
        checkpointer: Optional[GraphCheckpointStore] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.graph = graph
        self.supervisor = supervisor
        self.max_steps = max_steps
        self.checkpointer = checkpointer
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.run_id: Optional[str] = None

    async def _run_node(self, node: GraphNode, state: GraphState, step_index: int) -> WorkerResult:
        async def _worker(ctx: WorkerContext) -> Any:
            result = node.fn(state.data)
            if hasattr(result, "__await__"):
                return await result
            return result

        return await self.supervisor.run(
            step_id=f"{self.run_id}:{node.id}:{step_index}",
            worker=_worker,
            payload={"node": node.id, "step_index": step_index},
            worker_id=node.worker_id,
            **node.supervisor_kwargs,
        )

    def _next(self, node_id: str, state: GraphState) -> Optional[str]:
        edges = self.graph.outgoing(node_id)
        if not edges:
            return None
        for edge in edges:
            if edge.condition is None or edge.condition(state.data):
                return edge.target
        # No hubo arista tomada: si hay un finish point, detener; si no, error.
        if self.graph._finish == node_id:
            return None
        return None

    async def run(self, *, initial_data: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> GraphState:
        self.run_id = run_id or str(uuid.uuid4())
        state = GraphState(data=dict(initial_data or {}))
        current = self.graph._entry
        step_index = 0
        start = time.perf_counter()

        while current is not None and step_index < self.max_steps:
            node = self.graph._nodes[current]
            state.current_node = current

            # Human-in-the-loop: si el nodo exige aprobación, pausamos ANTES de
            # ejecutarlo y persistimos un checkpoint marcado como pausado.
            if node.require_approval is not None:
                if self.checkpointer is not None:
                    self.checkpointer.save(
                        run_id=self.run_id,
                        step_index=step_index,
                        state=state,
                        finished=False,
                        tenant_id=self.tenant_id,
                        session_id=self.session_id,
                        paused=True,
                        paused_node=current,
                    )
                raise GraphPaused(
                    f"node '{current}' requires approval ('{node.require_approval}')",
                    node_id=current,
                    action=node.require_approval,
                    run_id=self.run_id,
                )

            result = await self._run_node(node, state, step_index)
            if result.failed:
                raise GraphError(
                    f"node '{current}' failed after {result.attempts} attempts: {result.error}"
                )
            state.data[f"__out__{current}"] = result.output
            state.last_output = result.output
            state.visited.append(current)
            step_index += 1

            finished = current == self.graph._finish
            if self.checkpointer is not None:
                self.checkpointer.save(
                    run_id=self.run_id,
                    step_index=step_index,
                    state=state,
                    finished=finished,
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                )

            if finished:
                break
            current = self._next(current, state)

        if step_index >= self.max_steps:
            raise GraphError(f"exceeded max_steps={self.max_steps} (possible cycle without finish)")

        state.current_node = current
        return state

    async def approve(
        self,
        run_id: str,
        *,
        approver: Optional[str] = None,
        rbac: "object | None" = None,
        action: Optional[str] = None,
    ) -> GraphState:
        """Reanuda un grafo pausado por HIL tras aprobar el nodo pendiente.

        Si se pasa ``rbac`` (un ``RBACEngine``), valida que ``approver`` tenga
        el permiso ``action`` (por defecto el ``require_approval`` del nodo
        pausado). Si no tiene permiso, lanza ``RBACError`` (reutiliza
        ``ciel.enterprise.rbac``). Tras aprobar, ejecuta el nodo y continúa el
        grafo desde allí.

        Requiere un checkpointer (el grafo debe haber sido pausado con uno).
        """
        if self.checkpointer is None:
            raise GraphError("approve requires a checkpointer (pause happened with one)")
        self.run_id = run_id
        payload = self.checkpointer.load(
            run_id=run_id, tenant_id=self.tenant_id, session_id=self.session_id
        )
        if payload is None:
            raise GraphError(f"no checkpoint found for run_id '{run_id}'")
        if not payload.get("paused"):
            raise GraphError(f"run_id '{run_id}' is not paused (no HIL approval pending)")
        if payload.get("finished"):
            state = GraphState.from_snapshot(payload["state"])
            state.current_node = None
            return state

        paused_node = payload["paused_node"]
        node = self.graph._nodes.get(paused_node)
        if node is None:
            raise GraphError(f"paused node '{paused_node}' no longer exists in graph")
        action = action or node.require_approval
        if rbac is not None and action is not None:
            rbac.check(approver, action, tenant_id=self.tenant_id)

        state = GraphState.from_snapshot(payload["state"])
        step_index = int(payload.get("step_index", 0))
        # Ejecuta el nodo pausado y continúa desde allí (no re-ejecuta previos).
        state.current_node = paused_node
        result = await self._run_node(node, state, step_index)
        if result.failed:
            raise GraphError(
                f"node '{paused_node}' failed after approval: {result.error}"
            )
        state.data[f"__out__{paused_node}"] = result.output
        state.last_output = result.output
        state.visited.append(paused_node)
        step_index += 1
        current = self._next(paused_node, state)

        while current is not None and step_index < self.max_steps:
            node = self.graph._nodes[current]
            state.current_node = current
            result = await self._run_node(node, state, step_index)
            if result.failed:
                raise GraphError(
                    f"node '{current}' failed after {result.attempts} attempts: {result.error}"
                )
            state.data[f"__out__{current}"] = result.output
            state.last_output = result.output
            state.visited.append(current)
            step_index += 1
            finished = current == self.graph._finish
            self.checkpointer.save(
                run_id=self.run_id,
                step_index=step_index,
                state=state,
                finished=finished,
                tenant_id=self.tenant_id,
                session_id=self.session_id,
            )
            if finished:
                break
            current = self._next(current, state)

        if step_index >= self.max_steps:
            raise GraphError(f"exceeded max_steps={self.max_steps} during approve")
        state.current_node = current
        return state

    async def deny(self, run_id: str, *, reason: Optional[str] = None) -> None:
        """Marca un grafo pausado por HIL como denegado y detiene el flujo.

        Persiste el checkpoint como no-pausado y no-finalizado; el estado
        queda libre para inspección pero el grafo no continúa. Lanza
        ``GraphApprovalDenied`` para que el llamador sepa que fue rechazado.
        """
        if self.checkpointer is None:
            raise GraphError("deny requires a checkpointer")
        self.run_id = run_id
        payload = self.checkpointer.load(
            run_id=run_id, tenant_id=self.tenant_id, session_id=self.session_id
        )
        if payload is None:
            raise GraphError(f"no checkpoint found for run_id '{run_id}'")
        if not payload.get("paused"):
            raise GraphError(f"run_id '{run_id}' is not paused")
        # Persiste como no-pausado para que resume/approve no lo retomen.
        state = GraphState.from_snapshot(payload["state"])
        self.checkpointer.save(
            run_id=run_id,
            step_index=int(payload.get("step_index", 0)),
            state=state,
            finished=False,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            paused=False,
            paused_node=None,
        )
        raise GraphApprovalDenied(
            f"approval denied for run_id '{run_id}'"
 + (f": {reason}" if reason else "")
        )

    async def resume(self, *, run_id: str) -> GraphState:
        """Reanuda un grafo interrumpido desde su último checkpoint.

        Reconstruye el estado persistido y continúa desde el último nodo
        visitado. Si el checkpoint marca ``finished=True``, devuelve el estado
        tal cual (idempotente).
        """
        if self.checkpointer is None:
            raise GraphError("resume requires a checkpointer")
        self.run_id = run_id
        payload = self.checkpointer.load(
            run_id=run_id, tenant_id=self.tenant_id, session_id=self.session_id
        )
        if payload is None:
            raise GraphError(f"no checkpoint found for run_id '{run_id}'")
        if payload.get("finished"):
            state = GraphState.from_snapshot(payload["state"])
            state.current_node = None
            return state
        if payload.get("paused"):
            raise GraphPaused(
                f"run_id '{run_id}' is paused waiting for HIL approval",
                node_id=payload.get("paused_node") or "",
                action=(self.graph._nodes.get(payload.get("paused_node"))
                        and self.graph._nodes[payload["paused_node"]].require_approval)
                or "approve:*",
                run_id=run_id,
            )

        state = GraphState.from_snapshot(payload["state"])
        # Retomar desde el nodo SIGUIENTE al último completado (no re-ejecutar
        # el último visitado). Si no hay aristas salientes, el grafo terminó.
        if state.visited:
            current = self._next(state.visited[-1], state)
        else:
            current = self.graph._entry
        step_index = int(payload.get("step_index", 0))

        while current is not None and step_index < self.max_steps:
            node = self.graph._nodes[current]
            state.current_node = current
            result = await self._run_node(node, state, step_index)
            if result.failed:
                raise GraphError(
                    f"node '{current}' failed after {result.attempts} attempts: {result.error}"
                )
            state.data[f"__out__{current}"] = result.output
            state.last_output = result.output
            state.visited.append(current)
            step_index += 1

            finished = current == self.graph._finish
            self.checkpointer.save(
                run_id=self.run_id,
                step_index=step_index,
                state=state,
                finished=finished,
                tenant_id=self.tenant_id,
                session_id=self.session_id,
            )
            if finished:
                break
            current = self._next(current, state)

        if step_index >= self.max_steps:
            raise GraphError(f"exceeded max_steps={self.max_steps} during resume")
        state.current_node = current
        return state

    async def run_from(self, *, run_id: str, up_to_node: str, initial_data: Optional[Dict[str, Any]] = None) -> GraphState:
        """Time-travel: re-ejecuta el grafo desde el inicio hasta ``up_to_node``.

        Útil para reproducir/depurar un sub-tramo del flujo de forma
        determinista, con el mismo ``run_id`` (sobrescribe el checkpoint).
        """
        # Ejecuta normalmente pero se detiene al alcanzar up_to_node (inclusive).
        self.run_id = run_id
        state = GraphState(data=dict(initial_data or {}))
        current = self.graph._entry
        step_index = 0
        while current is not None and step_index < self.max_steps:
            node = self.graph._nodes[current]
            state.current_node = current
            result = await self._run_node(node, state, step_index)
            if result.failed:
                raise GraphError(f"node '{current}' failed: {result.error}")
            state.data[f"__out__{current}"] = result.output
            state.last_output = result.output
            state.visited.append(current)
            step_index += 1
            if self.checkpointer is not None:
                self.checkpointer.save(
                    run_id=self.run_id,
                    step_index=step_index,
                    state=state,
                    finished=(current == up_to_node),
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                )
            if current == up_to_node:
                break
            current = self._next(current, state)
        state.current_node = current
        return state
