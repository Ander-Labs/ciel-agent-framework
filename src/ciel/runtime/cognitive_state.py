"""Introspección / estado cognitivo explicable (Fase 19, v0.13.0).

Aditivo y offline-safe. Engancha ``Agent(introspection=...)`` sin reescribir
``api.py`` y:

* Inyecta un bloque ``[Estado cognitivo]`` en el system prompt (en ``_build_request``)
  con el último snapshot conocido del agente, para que el modelo sea consciente
  de su propio estado (vuelve a inyectar el contexto de la introspección).
* Registra un ``CognitiveSnapshot`` post-run en ``cognitive_state_log`` del
  ``StateBackend`` (aislado por tenant/session).
* Expone ``Agent.introspect()`` para volcar los últimos snapshots.

Reusa ``EpisodicStore`` (conteo de turnos) y ``DeterministicEmbeddingProvider``
(embedding del estado, offline). El RAG (``retrieved_context_ids``) queda como
None cuando el agente no usa RAG; el campo es opcional.

Degrada graceful: si no se instala, ``_cognitive`` no existe y el run no cambia.
"""

from __future__ import annotations

import functools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ciel.rag.embeddings import DeterministicEmbeddingProvider
from ciel.runtime.memory_episodic import EpisodicStore
from ciel.runtime.state_backend import StateBackend
from ciel.runtime.tools import ChatMessage, ChatRequest


@dataclass
class CognitiveSnapshot:
    """Instantánea del estado cognitivo del agente en un run."""

    tenant_id: Optional[str]
    session_id: str
    active_prompt_version: Optional[str] = None
    memory_turn_count: int = 0
    retrieved_context_ids: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    had_failure: bool = False
    confidence: float = 1.0
    rationale: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "active_prompt_version": self.active_prompt_version,
            "memory_turn_count": self.memory_turn_count,
            "retrieved_context_ids": list(self.retrieved_context_ids),
            "tool_calls": list(self.tool_calls),
            "had_failure": self.had_failure,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveSnapshot":
        return cls(
            tenant_id=data.get("tenant_id"),
            session_id=data.get("session_id", ""),
            active_prompt_version=data.get("active_prompt_version"),
            memory_turn_count=int(data.get("memory_turn_count", 0)),
            retrieved_context_ids=list(data.get("retrieved_context_ids") or []),
            tool_calls=list(data.get("tool_calls") or []),
            had_failure=bool(data.get("had_failure", False)),
            confidence=float(data.get("confidence", 1.0)),
            rationale=data.get("rationale", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class IntrospectionReport:
    """Agrega snapshots de una sesión en un reporte introspectivo."""

    tenant_id: Optional[str]
    session_id: str
    snapshots: List[CognitiveSnapshot] = field(default_factory=list)

    @property
    def latest(self) -> Optional[CognitiveSnapshot]:
        return self.snapshots[0] if self.snapshots else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "snapshot_count": len(self.snapshots),
            "snapshots": [s.to_dict() for s in self.snapshots],
        }


@dataclass
class IntrospectionConfig:
    enabled: bool = True
    inject_into_prompt: bool = True
    embedding_dim: int = 64

    @classmethod
    def disabled(cls) -> "IntrospectionConfig":
        return cls(enabled=False)


class CognitiveState:
    """State holder de introspección para un ``Agent`` (aditivo, offline)."""

    def __init__(
        self,
        store: Optional[EpisodicStore],
        backend: StateBackend,
        config: Optional[IntrospectionConfig] = None,
        session_id: Optional[str] = None,
    ) -> None:
        # store: EpisodicStore (para conteo de turnos); backend: StateBackend (log).
        # ``backend`` es obligatorio: si el agente no tiene memoria, el caller
        # debe pasar un ``StateBackend`` persistente (defaulteado a una instancia
        # por-proceso) para que los snapshots sobrevivan al run y sean consultables.
        # ``session_id`` es estable por agente (no transitorio por run) para que
        # la inyección y la introspección coincidan run a run.
        self.store = store
        self.backend = backend
        self.config = config or IntrospectionConfig()
        self._embedder = DeterministicEmbeddingProvider(dim=self.config.embedding_dim)
        self.session_id = session_id or str(uuid.uuid4())
        self.tenant_id: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # ------------------------------------------------------------------ #
    def build_snapshot(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        response: Any,
        active_prompt_version: Optional[str] = None,
        retrieved_context_ids: Optional[List[str]] = None,
    ) -> CognitiveSnapshot:
        tool_results = response.tool_results if hasattr(response, "tool_results") else []
        had_failure = any(getattr(r, "error", None) for r in tool_results)
        tool_calls = [
            {"name": r.name, "error": getattr(r, "error", None)} for r in tool_results
        ]
        # conteo de turnos de memoria episódica (si hay store)
        memory_turn_count = 0
        if self.store is not None:
            recent = self.store.get_recent(
                tenant_id=tenant_id, session_id=session_id, limit=1000
            )
            memory_turn_count = len(recent)
        # confianza heurística determinista offline
        if had_failure:
            confidence = 0.3
            rationale = "fallo(s) de tool detectado(s) en el run"
        elif tool_calls:
            confidence = 0.8
            rationale = "run con uso de tools sin fallos"
        else:
            confidence = 1.0
            rationale = "run directo sin tools"
        return CognitiveSnapshot(
            tenant_id=tenant_id,
            session_id=session_id,
            active_prompt_version=active_prompt_version,
            memory_turn_count=memory_turn_count,
            retrieved_context_ids=list(retrieved_context_ids or []),
            tool_calls=tool_calls,
            had_failure=had_failure,
            confidence=confidence,
            rationale=rationale,
        )

    def record(self, snapshot: CognitiveSnapshot) -> None:
        """Persiste el snapshot en ``cognitive_state_log`` (tenant-filtered)."""
        try:
            self.backend.state_log_append(
                tenant_id=snapshot.tenant_id,
                session_id=snapshot.session_id,
                prompt_version=snapshot.active_prompt_version,
                value_json=_dump(snapshot.to_dict()),
                created_at=snapshot.created_at
                or datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # pragma: no cover - introspección nunca rompe el run
            pass

    def get_recent(
        self, *, tenant_id: Optional[str], session_id: str, limit: int = 16
    ) -> IntrospectionReport:
        snapshots: List[CognitiveSnapshot] = []
        try:
            rows = self.backend.state_log_get_recent(
                tenant_id=tenant_id, session_id=session_id, limit=limit
            )
            for row in rows:
                try:
                    snapshots.append(CognitiveSnapshot.from_dict(row))
                except Exception:  # pragma: no cover - defensivo
                    continue
        except Exception:  # pragma: no cover - defensivo
            pass
        return IntrospectionReport(
            tenant_id=tenant_id, session_id=session_id, snapshots=snapshots
        )

    def latest_block(self, *, tenant_id: Optional[str], session_id: str) -> Optional[str]:
        """Devuelve el bloque ``[Estado cognitivo]`` a inyectar, o None."""
        if not self.config.inject_into_prompt:
            return None
        report = self.get_recent(tenant_id=tenant_id, session_id=session_id, limit=1)
        snap = report.latest
        if snap is None:
            return None
        lines = [
            f"Versión de prompt activa: {snap.active_prompt_version or 'instructions (no versionado)'}",
            f"Turnos de memoria acumulados: {snap.memory_turn_count}",
            f"Tool calls en el último run: {len(snap.tool_calls)}",
            f"Falló en el último run: {'sí' if snap.had_failure else 'no'}",
            f"Confianza estimada: {snap.confidence:.2f}",
            f"Rationale: {snap.rationale}",
        ]
        return "[Estado cognitivo]\n" + "\n".join(lines)

    def embed_state(self, snapshot: CognitiveSnapshot) -> List[float]:
        """Embedding determinista del estado (offline)."""
        text = (
            f"failure={snapshot.had_failure} tools={len(snapshot.tool_calls)} "
            f"conf={snapshot.confidence:.2f} turns={snapshot.memory_turn_count}"
        )
        return self._embedder.embed_one(text)


# Backend por-proceso para agentes sin memoria (determinista, in-memory SQLite).
_DEFAULT_COGNITIVE_BACKEND: Optional[StateBackend] = None


def _default_backend() -> StateBackend:
    global _DEFAULT_COGNITIVE_BACKEND
    if _DEFAULT_COGNITIVE_BACKEND is None:
        _DEFAULT_COGNITIVE_BACKEND = SqliteStateBackend_memory()
    return _DEFAULT_COGNITIVE_BACKEND


def SqliteStateBackend_memory() -> StateBackend:
    from ciel.runtime.state_backend import SqliteStateBackend

    return SqliteStateBackend(":memory:")


def install_cognitive_state_support(agent_cls: Any) -> Any:
    """Engancha ``introspection=`` / ``introspection_config=`` sin reescribir api.py.

    Idempotente.
    """
    if getattr(agent_cls, "_cognitive_installed", False):
        return agent_cls
    original_init = agent_cls.__init__
    original_build = agent_cls._build_request
    original_arun = agent_cls.arun

    @functools.wraps(original_init)
    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        intro_arg = kwargs.pop("introspection", None)
        intro_config = kwargs.pop("introspection_config", None)
        original_init(self, *args, **kwargs)

        config = intro_config or IntrospectionConfig()
        if intro_arg is False or (intro_arg is None and intro_config is None):
            config = config.disabled()

        # Resolver backend + store: reutiliza el EpisodicStore de memoria si existe
        # (así el log cognitivo vive en el mismo backend que la memoria del agente).
        store = None
        backend: StateBackend = _default_backend()
        session_id: Optional[str] = None
        mem = getattr(self, "_memory", None)
        if mem is not None and getattr(mem, "store", None) is not None:
            store = mem.store
            be = getattr(store, "_backend", None)
            if be is not None:
                backend = be
            session_id = mem.session_id() if mem.enabled else None
        if store is None:
            store = EpisodicStore(backend)
        if session_id is None:
            session_id = str(uuid.uuid4())
        self._cognitive = CognitiveState(
            store=store, backend=backend, config=config, session_id=session_id
        )

    @functools.wraps(original_build)
    def _patched_build(self: Any, prompt, *, tenant_id=None, session_id=None, **kw) -> Any:
        request = original_build(
            self, prompt, tenant_id=tenant_id, session_id=session_id, **kw
        )
        cog = getattr(self, "_cognitive", None)
        if cog is not None and cog.enabled:
            block = cog.latest_block(
                tenant_id=_effective_tenant(self, tenant_id), session_id=cog.session_id
            )
            if block:
                # ChatRequest es frozen -> reconstruimos, no reasignamos.
                new_messages = list(request.messages) + [
                    ChatMessage(role="system", content=block)
                ]
                request = ChatRequest(
                    messages=tuple(new_messages),
                    tools=request.tools,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    extra=request.extra,
                )
        return request

    @functools.wraps(original_arun)
    async def _patched_arun(
        self: Any, prompt, *, tenant_id=None, max_turns=10, limit=32
    ) -> Any:
        eff_tenant = _effective_tenant(self, tenant_id)
        resp = await original_arun(
            self, prompt, tenant_id=tenant_id, max_turns=max_turns, limit=limit
        )
        cog = getattr(self, "_cognitive", None)
        if cog is not None and cog.enabled:
            cog.tenant_id = eff_tenant
            try:
                snap = cog.build_snapshot(
                    tenant_id=eff_tenant,
                    session_id=cog.session_id,
                    response=resp,
                )
                cog.record(snap)
            except Exception:  # pragma: no cover - introspección nunca rompe el run
                pass
        return resp

    agent_cls.__init__ = _patched_init  # type: ignore[assignment]
    agent_cls._build_request = _patched_build  # type: ignore[assignment]
    agent_cls.arun = _patched_arun  # type: ignore[assignment]
    agent_cls._cognitive_installed = True  # type: ignore[attr-defined]

    # Helper de consulta expuesto en la instancia.
    def _introspect(self: Any, *, limit: int = 16) -> IntrospectionReport:
        cog = getattr(self, "_cognitive", None)
        if cog is None:
            return IntrospectionReport(tenant_id=None, session_id="", snapshots=[])
        return cog.get_recent(
            tenant_id=cog.tenant_id, session_id=cog.session_id, limit=limit
        )

    agent_cls.introspect = _introspect  # type: ignore[attr-defined]
    return agent_cls


def _effective_tenant(agent: Any, tenant_id: Optional[str] = None) -> Optional[str]:
    if tenant_id:
        return tenant_id
    mem = getattr(agent, "_memory", None)
    if mem is not None and mem.enabled:
        return getattr(agent, "tenant_id", None) or "default"
    return getattr(agent, "tenant_id", None) or "default"


def _dump(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:  # pragma: no cover - defensivo
        return json.dumps({"repr": repr(value)})


__all__ = [
    "CognitiveSnapshot",
    "IntrospectionReport",
    "IntrospectionConfig",
    "CognitiveState",
    "install_cognitive_state_support",
]
