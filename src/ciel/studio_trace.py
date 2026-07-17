"""Ciel Studio — trazabilidad de grafos y replay/time-travel (Fase 13 / F20).

Extiende *Ciel Studio* con **graph view + replay/time-travel** sobre el
runtime de grafos ya existente (``ciel.orchestration.graph``). Registra cada
``save`` del ``GraphCheckpointStore`` para reconstruir, paso a paso, la
evolución del estado de un ``run`` de grafo y permitir viaje en el tiempo
(replay).

Diseño:

- **Offline-safe**: el store es en memoria, no requiere BD ni red. Se apoya en
  el ``GraphCheckpointStore`` (que ya usa ``MemoryStore``) pero mantiene su
  propia historia completa de checkpoints (el checkpointer sólo conserva el
  último; el trace conserva *todos*).
- **No invasivo**: ``attach_trace`` envuelve el ``save`` del checkpointer sin
  romper su valor de retorno ni su semántica (fachada, estilo ``studio.py``).
- **Autónomo**: NO importa ``studio.py`` para evitar acoplar con el subagente
  de F19; expone su propio singleton ``get_trace_store()``.

El router FastAPI ``/v1/studio/trace`` se integra en ``ciel serve`` y puede
sondearse (polling) desde una UI de replay; los tests usan ``TestClient``.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:  # FastAPI es opcional en entornos mínimos.
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - depends on optional extra
    APIRouter = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Modelo de datos (en memoria)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TraceStep:
    """Un checkpoint registrado de un ``run`` de grafo.

    Inmutable (frozen) porque es un hecho histórico: una vez guardado, el
    estado de ese paso no cambia (es la base del time-travel).
    """

    run_id: str
    step_index: int
    tenant_id: Optional[str]
    session_id: Optional[str]
    paused: bool
    paused_node: Optional[str]
    finished: bool
    checkpoint_id: str
    state_snapshot: Dict[str, Any]
    ts: float

    def to_dict(self) -> Dict[str, Any]:
        """Serializa el paso a un dict JSON-friendly."""
        return {
            "run_id": self.run_id,
            "step_index": self.step_index,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "paused": self.paused,
            "paused_node": self.paused_node,
            "finished": self.finished,
            "checkpoint_id": self.checkpoint_id,
            "state_snapshot": self.state_snapshot,
            "ts": self.ts,
        }


class GraphTraceStore:
    """Store en memoria de la historia de checkpoints de grafos por run/tenant.

    Offline-safe: no persiste a disco ni requiere red. Conserva **todos** los
    ``save`` de un ``GraphCheckpointStore`` (no sólo el último), lo que habilita
    el replay step a step y el graph view.
    """

    def __init__(self) -> None:
        # run_id -> lista de pasos (en orden de inserción; se ordena al leer).
        self._runs: Dict[str, List[TraceStep]] = {}

    # --- escritura ---------------------------------------------------------
    def record_checkpoint(self, payload: Dict[str, Any]) -> TraceStep:
        """Registra un checkpoint guardado.

        El ``payload`` debe traer al menos: ``run_id``, ``step_index``,
        ``tenant_id``, ``session_id``, ``paused``, ``paused_node``,
        ``state_snapshot``. Campos opcionales pero recomendados: ``finished``,
        ``checkpoint_id``. Si faltan, se rellenan con valores por defecto.
        """
        step = TraceStep(
            run_id=payload["run_id"],
            step_index=int(payload.get("step_index", 0)),
            tenant_id=payload.get("tenant_id"),
            session_id=payload.get("session_id"),
            paused=bool(payload.get("paused", False)),
            paused_node=payload.get("paused_node"),
            finished=bool(payload.get("finished", False)),
            checkpoint_id=payload.get("checkpoint_id") or "",
            state_snapshot=dict(payload.get("state_snapshot", {})),
            ts=float(payload.get("ts", time.time())),
        )
        self._runs.setdefault(step.run_id, []).append(step)
        return step

    # --- lectura -----------------------------------------------------------
    def steps_of(self, run_id: str) -> List[TraceStep]:
        """Devuelve los pasos de un run ordenados por ``step_index`` (tie-break ts)."""
        steps = list(self._runs.get(run_id, []))
        steps.sort(key=lambda s: (s.step_index, s.ts))
        return steps

    def get_run(self, run_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Devuelve el resumen de un run con sus ``steps`` ordenados.

        Filtra por ``tenant_id`` si se indica (coincide con el tenant del run).
        """
        steps = self.steps_of(run_id)
        if not steps:
            return None
        if tenant_id is not None and steps[0].tenant_id != tenant_id:
            return None
        first = steps[0]
        return {
            "run_id": run_id,
            "tenant_id": first.tenant_id,
            "session_id": first.session_id,
            "step_count": len(steps),
            "finished": any(s.finished for s in steps),
            "paused": any(s.paused for s in steps),
            "last_step_index": steps[-1].step_index,
            "steps": [s.to_dict() for s in steps],
        }

    def list_runs(self, *, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista los runs registrados (filtrado opcional por ``tenant_id``).

        Cada entrada es un resumen: ``run_id``, ``tenant_id``, ``session_id``,
        ``step_count``, ``finished``, ``paused``, ``last_step_index``. Ordenado
        por ``ts`` del último paso (más reciente primero).
        """
        summaries: List[Dict[str, Any]] = []
        for run_id, steps in self._runs.items():
            if not steps:
                continue
            first = steps[0]
            if tenant_id is not None and first.tenant_id != tenant_id:
                continue
            ordered = sorted(steps, key=lambda s: (s.step_index, s.ts))
            last = ordered[-1]
            summaries.append(
                {
                    "run_id": run_id,
                    "tenant_id": first.tenant_id,
                    "session_id": first.session_id,
                    "step_count": len(ordered),
                    "finished": any(s.finished for s in ordered),
                    "paused": any(s.paused for s in ordered),
                    "last_step_index": last.step_index,
                    "last_ts": last.ts,
                }
            )
        summaries.sort(key=lambda r: r["last_ts"], reverse=True)
        return summaries

    def replay(self, run_id: str, *, tenant_id: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Reconstruye el estado del grafo paso a paso (time-travel).

        Devuelve la lista de ``state_snapshot`` de cada checkpoint, en orden de
        ``step_index``. Cada elemento es el estado completo reconstruido en ese
        paso; la UI puede reproducirlos como una animación del graph view.
        """
        run = self.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            return None
        return [step["state_snapshot"] for step in run["steps"]]

    # --- snapshot ----------------------------------------------------------
    def snapshot(self, *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        runs = self.list_runs(tenant_id=tenant_id)
        return {
            "runs": runs,
            "counts": {
                "runs": len(runs),
                "steps": sum(r["step_count"] for r in runs),
                "finished_runs": sum(1 for r in runs if r["finished"]),
                "paused_runs": sum(1 for r in runs if r["paused"]),
            },
        }


# Singleton por proceso (la UI y el runtime comparten el mismo store).
_DEFAULT_TRACE_STORE: Optional[GraphTraceStore] = None


def get_trace_store() -> GraphTraceStore:
    """Devuelve el store de trazabilidad por defecto (singleton)."""
    global _DEFAULT_TRACE_STORE
    if _DEFAULT_TRACE_STORE is None:
        _DEFAULT_TRACE_STORE = GraphTraceStore()
    return _DEFAULT_TRACE_STORE


def reset_trace_store() -> None:
    """Reinicia el store por defecto (útil en tests)."""
    global _DEFAULT_TRACE_STORE
    _DEFAULT_TRACE_STORE = None


def get_trace_summary(*, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Devuelve un resumen autónomo de la trazabilidad (counts de runs).

    No acopla con ``studio.py``: consulta directamente el singleton del trace.
    """
    return get_trace_store().snapshot(tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Enganche al GraphCheckpointStore (fachada, no rompe la API existente)
# ---------------------------------------------------------------------------
def attach_trace(checkpointer: Any, store: Optional[GraphTraceStore] = None) -> GraphTraceStore:
    """Envuelve ``save`` de un ``GraphCheckpointStore`` para registrar en trace.

    Es una fachada: NO cambia la firma ni el valor de retorno de ``save``
    (sigue devolviendo ``checkpoint_id``). Tras cada ``save`` original, registra
    un ``TraceStep`` en el ``GraphTraceStore`` (por defecto el singleton).

    Args:
        checkpointer: instancia de ``ciel.orchestration.graph.GraphCheckpointStore``.
        store: ``GraphTraceStore`` opcional; si se omite usa el singleton.

    Returns:
        El store usado (para montarlo en el router).
    """
    st = store or get_trace_store()
    orig_save = checkpointer.save

    @functools.wraps(orig_save)
    def _traced_save(
        self: Any,
        *,
        run_id: str,
        step_index: int,
        state: Any,
        finished: bool,
        tenant_id: Optional[str],
        session_id: Optional[str],
        paused: bool = False,
        paused_node: Optional[str] = None,
        **kw: Any,
    ) -> str:
        checkpoint_id = orig_save(
            run_id=run_id,
            step_index=step_index,
            state=state,
            finished=finished,
            tenant_id=tenant_id,
            session_id=session_id,
            paused=paused,
            paused_node=paused_node,
            **kw,
        )
        # El estado puede ser GraphState (con .snapshot()) o un dict serializable.
        state_snapshot: Dict[str, Any]
        if hasattr(state, "snapshot"):
            state_snapshot = state.snapshot()  # type: ignore[attr-defined]
        else:
            state_snapshot = dict(state) if isinstance(state, dict) else {"repr": repr(state)}
        st.record_checkpoint(
            {
                "run_id": run_id,
                "step_index": step_index,
                "tenant_id": tenant_id,
                "session_id": session_id,
                "paused": paused,
                "paused_node": paused_node,
                "finished": finished,
                "checkpoint_id": checkpoint_id,
                "state_snapshot": state_snapshot,
                "ts": time.time(),
            }
        )
        return checkpoint_id

    # Enlazamos como método del checkpointer (bound method) para preservar self.
    checkpointer.save = _traced_save.__get__(checkpointer, type(checkpointer))  # type: ignore[assignment]
    checkpointer._trace_store = st  # type: ignore[attr-defined]
    return st


# ---------------------------------------------------------------------------
# Router FastAPI (Ciel Studio / trace)
# ---------------------------------------------------------------------------
def create_trace_router(
    store: Optional[GraphTraceStore] = None,
    path: str = "/v1/studio/trace",
):
    """Crea un router FastAPI que expone el replay/time-travel de grafos.

    Rutas:
        ``GET {path}``              -> snapshot (runs + counts)
        ``GET {path}/runs``         -> lista de runs (filtro ``?tenant=``)
        ``GET {path}/runs/{run_id}``-> pasos del run en orden
        ``GET {path}/runs/{run_id}/replay`` -> estados reconstruidos step a step
        ``GET {path}/health``       -> ``{"status": "ok", "channel": "trace"}``

    Offline-safe: no requiere red; se sondea desde la UI de replay.
    """
    if not _FASTAPI_AVAILABLE:  # pragma: no cover - depends on optional extra
        raise RuntimeError("FastAPI no disponible; instala el extra 'server' para ciel serve")

    st = store or get_trace_store()
    router = APIRouter()

    @router.get(path)
    async def trace_snapshot(tenant: Optional[str] = None):
        return JSONResponse(st.snapshot(tenant_id=tenant))

    @router.get(f"{path}/runs")
    async def trace_runs(tenant: Optional[str] = None):
        return JSONResponse(st.list_runs(tenant_id=tenant))

    @router.get(f"{path}/runs/{{run_id}}")
    async def trace_run(run_id: str, tenant: Optional[str] = None):
        run = st.get_run(run_id, tenant_id=tenant)
        if run is None:
            return JSONResponse({"error": "run_not_found", "run_id": run_id}, status_code=404)
        return JSONResponse(run)

    @router.get(f"{path}/runs/{{run_id}}/replay")
    async def trace_replay(run_id: str, tenant: Optional[str] = None):
        states = st.replay(run_id, tenant_id=tenant)
        if states is None:
            return JSONResponse({"error": "run_not_found", "run_id": run_id}, status_code=404)
        return JSONResponse({"run_id": run_id, "steps": states})

    @router.get(f"{path}/health")
    async def trace_health():
        return JSONResponse({"status": "ok", "channel": "trace"})

    return router


__all__ = [
    "TraceStep",
    "GraphTraceStore",
    "get_trace_store",
    "reset_trace_store",
    "get_trace_summary",
    "attach_trace",
    "create_trace_router",
]
