"""Ciel Studio — dashboard mínimo de observabilidad (Fase 13 / F19).

Expone, sin red ni providers reales, un panel operativo de lo que el agente
está haciendo: sesiones, loops y estado cognitivo. Es la base de *Ciel
Studio* (Web UI + observabilidad visual) y está diseñado para ser:

- **Offline-safe**: el store es en memoria, no requiere BD ni red.
- **Multitenant**: cada registro se aísla por ``tenant_id``.
- **Fachada**: se monta sobre el ``Agent`` existente (no lo reemplaza).

El router FastAPI ``/v1/studio`` se integra en ``ciel serve`` y puede
sondearse (polling) desde una UI mínima; los tests usan fakes.
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from dataclasses import dataclass, field
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
@dataclass
class SessionRecord:
    """Una ejecución de un agente (un ``run``/``arun``)."""

    session_id: str
    tenant_id: str
    agent: str
    prompt: str = ""
    text: str = ""
    finish_reason: str = "stop"
    tool_calls: int = 0
    turns: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class LoopRecord:
    """Un ciclo de bucle autónomo (``ciel loop run``)."""

    loop_id: str
    tenant_id: str
    agent: str
    status: str = "running"
    steps: int = 0
    last_event: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class StudioStore:
    """Store en memoria de sesiones/loops por tenant.

    Offline-safe: no persiste a disco ni requiere red. Para producción se
    puede sustituir por un ``MemoryStore`` remoto sin tocar la API.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._loops: Dict[str, LoopRecord] = {}
        self._lock = asyncio.Lock()

    # --- sesiones ----------------------------------------------------------
    def record_session(
        self,
        *,
        tenant_id: str,
        agent: str,
        prompt: str = "",
        text: str = "",
        finish_reason: str = "stop",
        tool_calls: int = 0,
        turns: int = 0,
        session_id: Optional[str] = None,
    ) -> SessionRecord:
        sid = session_id or f"sess-{uuid.uuid4().hex[:12]}"
        now = time.time()
        rec = SessionRecord(
            session_id=sid,
            tenant_id=tenant_id,
            agent=agent,
            prompt=prompt,
            text=text,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            turns=turns,
            created_at=now,
            updated_at=now,
        )
        self._sessions[sid] = rec
        return rec

    def update_session(self, session_id: str, **changes: Any) -> Optional[SessionRecord]:
        rec = self._sessions.get(session_id)
        if rec is None:
            return None
        for k, v in changes.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.updated_at = time.time()
        return rec

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return self._sessions.get(session_id)

    def list_sessions(self, *, tenant_id: Optional[str] = None) -> List[SessionRecord]:
        recs = list(self._sessions.values())
        if tenant_id is not None:
            recs = [r for r in recs if r.tenant_id == tenant_id]
        return sorted(recs, key=lambda r: r.updated_at, reverse=True)

    # --- loops -------------------------------------------------------------
    def record_loop(
        self,
        *,
        tenant_id: str,
        agent: str,
        loop_id: Optional[str] = None,
        status: str = "running",
    ) -> LoopRecord:
        lid = loop_id or f"loop-{uuid.uuid4().hex[:12]}"
        now = time.time()
        rec = LoopRecord(
            loop_id=lid,
            tenant_id=tenant_id,
            agent=agent,
            status=status,
            created_at=now,
            updated_at=now,
        )
        self._loops[lid] = rec
        return rec

    def update_loop(self, loop_id: str, **changes: Any) -> Optional[LoopRecord]:
        rec = self._loops.get(loop_id)
        if rec is None:
            return None
        for k, v in changes.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.updated_at = time.time()
        return rec

    def list_loops(self, *, tenant_id: Optional[str] = None) -> List[LoopRecord]:
        recs = list(self._loops.values())
        if tenant_id is not None:
            recs = [r for r in recs if r.tenant_id == tenant_id]
        return sorted(recs, key=lambda r: r.updated_at, reverse=True)

    # --- snapshot ----------------------------------------------------------
    def snapshot(self, *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        sessions = self.list_sessions(tenant_id=tenant_id)
        loops = self.list_loops(tenant_id=tenant_id)
        return {
            "sessions": [self._serialize(s) for s in sessions],
            "loops": [self._serialize(l) for l in loops],
            "counts": {
                "sessions": len(sessions),
                "loops": len(loops),
                "running_loops": sum(1 for l in loops if l.status == "running"),
            },
        }

    @staticmethod
    def _serialize(rec: Any) -> Dict[str, Any]:
        return {
            "id": rec.session_id if isinstance(rec, SessionRecord) else rec.loop_id,
            "type": "session" if isinstance(rec, SessionRecord) else "loop",
            "tenant_id": rec.tenant_id,
            "agent": rec.agent,
            "updated_at": rec.updated_at,
            **{
                k: getattr(rec, k)
                for k in (
                    "prompt",
                    "text",
                    "finish_reason",
                    "tool_calls",
                    "turns",
                    "status",
                    "steps",
                    "last_event",
                )
                if hasattr(rec, k)
            },
        }


# Singleton por proceso (la UI y el agente comparten el mismo store).
_DEFAULT_STORE: Optional[StudioStore] = None


def get_studio_store() -> StudioStore:
    """Devuelve el store de studio por defecto (singleton)."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = StudioStore()
    return _DEFAULT_STORE


def reset_studio_store() -> None:
    """Reinicia el store por defecto (útil en tests)."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = None


# ---------------------------------------------------------------------------
# Enganche al Agent (fachada, no rompe la API existente)
# ---------------------------------------------------------------------------
def _extract_meta(resp: Any) -> Dict[str, Any]:
    """Extrae metadatos de un ``AgentResponse`` de forma defensiva."""
    meta: Dict[str, Any] = {
        "text": "",
        "finish_reason": "stop",
        "tool_calls": 0,
        "turns": 0,
    }
    try:
        meta["text"] = getattr(resp, "text", "") or ""
    except Exception:
        pass
    try:
        meta["finish_reason"] = getattr(resp, "finish_reason", "stop") or "stop"
    except Exception:
        pass
    try:
        meta["tool_calls"] = len(getattr(resp, "tool_calls", []) or [])
    except Exception:
        pass
    try:
        loop_results = getattr(getattr(resp, "raw", None), "loop_results", None) or ()
        meta["turns"] = len(loop_results)
    except Exception:
        pass
    return meta


def install_studio_support(agent: Any, store: Optional[StudioStore] = None) -> StudioStore:
    """Envuelve ``run``/``arun`` del agente para registrar cada sesión.

    Es una fachada: NO cambia la firma ni el valor de retorno de los
    métodos originales. Tras cada ejecución, registra una ``SessionRecord``
    en el store (por defecto el singleton de studio).

    Args:
        agent: instancia de ``ciel.Agent``.
        store: ``StudioStore`` opcional; si se omite usa el singleton.

    Returns:
        El store usado (para montarlo en el router).
    """
    st = store or get_studio_store()
    agent_name = getattr(agent, "name", "ciel-agent")

    _orig_arun = agent.arun

    @functools.wraps(_orig_arun)
    async def _tracked_arun(prompt: str, *, tenant_id: Optional[str] = None, **kw: Any):
        effective_tenant = tenant_id or getattr(agent, "tenant_id", None) or "default"
        resp = await _orig_arun(prompt, tenant_id=tenant_id, **kw)
        meta = _extract_meta(resp)
        st.record_session(
            tenant_id=effective_tenant,
            agent=agent_name,
            prompt=prompt,
            text=meta["text"],
            finish_reason=meta["finish_reason"],
            tool_calls=meta["tool_calls"],
            turns=meta["turns"],
        )
        return resp

    agent.arun = _tracked_arun  # type: ignore[assignment]

    _orig_run = agent.run

    @functools.wraps(_orig_run)
    def _tracked_run(prompt: str, *, tenant_id: Optional[str] = None, **kw: Any):
        # Delegamos al ``arun`` ORIGINAL (no al wrappeado) para no registrar
        # dos veces: ``arun`` ya registra, y ``run`` es solo un wrapper sync.
        effective_tenant = tenant_id or getattr(agent, "tenant_id", None) or "default"
        resp = asyncio.run(_orig_arun(prompt, tenant_id=tenant_id, **kw))
        meta = _extract_meta(resp)
        st.record_session(
            tenant_id=effective_tenant,
            agent=agent_name,
            prompt=prompt,
            text=meta["text"],
            finish_reason=meta["finish_reason"],
            tool_calls=meta["tool_calls"],
            turns=meta["turns"],
        )
        return resp

    agent.run = _tracked_run  # type: ignore[assignment]
    agent._studio_store = st  # type: ignore[attr-defined]
    return st


# ---------------------------------------------------------------------------
# Router FastAPI (Ciel Studio)
# ---------------------------------------------------------------------------
def create_studio_router(store: Optional[StudioStore] = None, path: str = "/v1/studio"):
    """Crea un router FastAPI que expone el dashboard de studio.

    Rutas:
        ``GET {path}``           -> snapshot (sesiones + loops + counts)
        ``GET {path}/sessions``  -> lista de sesiones (filtro ``?tenant=``)
        ``GET {path}/loops``     -> lista de loops (filtro ``?tenant=``)
        ``GET {path}/health``    -> ``{"status": "ok", "channel": "studio"}``

    Offline-safe: no requiere red; se sondea desde la UI.
    """
    if not _FASTAPI_AVAILABLE:  # pragma: no cover - depends on optional extra
        raise RuntimeError("FastAPI no disponible; instala el extra 'server' para ciel serve")

    st = store or get_studio_store()
    router = APIRouter()

    @router.get(path)
    async def studio_snapshot(tenant: Optional[str] = None):
        return JSONResponse(st.snapshot(tenant_id=tenant))

    @router.get(f"{path}/sessions")
    async def studio_sessions(tenant: Optional[str] = None):
        return JSONResponse(
            [st._serialize(s) for s in st.list_sessions(tenant_id=tenant)]
        )

    @router.get(f"{path}/loops")
    async def studio_loops(tenant: Optional[str] = None):
        return JSONResponse(
            [st._serialize(l) for l in st.list_loops(tenant_id=tenant)]
        )

    @router.get(f"{path}/health")
    async def studio_health():
        return JSONResponse({"status": "ok", "channel": "studio"})

    return router


__all__ = [
    "StudioStore",
    "SessionRecord",
    "LoopRecord",
    "get_studio_store",
    "reset_studio_store",
    "install_studio_support",
    "create_studio_router",
]
