"""Memoria episódica del agente (Pilar A — Fase 17, v0.11.0).

Almacena las interacciones pasadas del agente por ``(tenant_id, session_id)``
con recuperación por ID, últimas-N y búsqueda por keywords. Es **offline-safe**:
no requiere red ni embeddings; se apoya en el ``StateBackend`` existente
(SQLite en dev, Postgres en prod) y aísla estrictamente por ``tenant_id``.

Decisión de diseño (corrige el riesgo de fuga cross-tenant de
``StateBackend.search``): todas las lecturas de memoria pasan por helpers del
backend que FILTRAN por ``tenant_id`` explícitamente. El ``EpisodicStore`` nunca
usa el ``search`` genérico sin filtro.

No se rompe la API pública: este módulo es nuevo y aditivo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence


@dataclass
class EpisodicMemory:
    """Una interacción persistida (un turno de mensaje del agente)."""

    id: str
    tenant_id: Optional[str]
    session_id: str
    role: str  # "user" | "assistant" | "system" | "tool"
    content: Any
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EpisodicMemory":
        return cls(
            id=data["id"],
            tenant_id=data.get("tenant_id"),
            session_id=data["session_id"],
            role=data["role"],
            content=data.get("content"),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata") or {},
        )


@dataclass
class MemoryConfig:
    """Configuración de memoria para un agente (degrada a 'sin memoria')."""

    enabled: bool = True
    recent_turns: int = 8  # cuántos episodios recientes inyectar por defecto
    search_limit: int = 5  # cuántos episodios por búsqueda semántica/keyword
    inject_into_system: bool = True  # prependear al system prompt

    @classmethod
    def disabled(cls) -> "MemoryConfig":
        return cls(enabled=False)


class EpisodicStore:
    """Store de memoria episódica sobre un ``StateBackend`` (aislado por tenant).

    Operaciones:
    * ``append`` — persiste un turno.
    * ``get_recent`` — últimos N episodios de una sesión (orden cronológico).
    * ``get_by_id`` — recupera un episodio por su ID.
    * ``search`` — búsqueda por keywords filtrada POR TENANT (no cross-tenant).
    * ``clear_session`` — borra la memoria de una sesión.
    * ``as_context`` — serializa episodios recientes como texto para el system.
    """

    def __init__(self, backend: Any, *, namespace: str = "episodic") -> None:
        # backend: ciel.runtime.state_backend.StateBackend
        self._backend = backend
        self._ns = namespace

    # -- helpers internos ----------------------------------------------------
    def _key(self, session_id: str, memory_id: str) -> str:
        return f"{self._ns}:{session_id}:{memory_id}"

    # -- escritura -----------------------------------------------------------
    def append(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        role: str,
        content: Any,
        metadata: Optional[dict] = None,
    ) -> EpisodicMemory:
        memory_id = str(uuid.uuid4())
        mem = EpisodicMemory(
            id=memory_id,
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._backend.memory_append(
            tenant_id=tenant_id,
            session_id=session_id,
            memory_id=memory_id,
            value=mem.to_dict(),
        )
        return mem

    # -- lectura -------------------------------------------------------------
    def get_recent(
        self, *, tenant_id: Optional[str], session_id: str, limit: int = 8
    ) -> List[EpisodicMemory]:
        rows = self._backend.memory_get_recent(
            tenant_id=tenant_id, session_id=session_id, limit=limit
        )
        out: List[EpisodicMemory] = []
        for row in rows:
            try:
                out.append(EpisodicMemory.from_dict(row))
            except (KeyError, TypeError):  # pragma: no cover - defensive
                continue
        # Orden cronológico ascendente (más antiguo primero).
        out.sort(key=lambda m: m.created_at)
        return out

    def get_by_id(
        self, *, tenant_id: Optional[str], session_id: str, memory_id: str
    ) -> Optional[EpisodicMemory]:
        row = self._backend.memory_get(
            tenant_id=tenant_id, session_id=session_id, memory_id=memory_id
        )
        if row is None:
            return None
        try:
            return EpisodicMemory.from_dict(row)
        except (KeyError, TypeError):  # pragma: no cover - defensive
            return None

    def search(
        self,
        *,
        tenant_id: Optional[str],
        session_id: Optional[str] = None,
        query: str,
        limit: int = 5,
    ) -> List[EpisodicMemory]:
        rows = self._backend.memory_search_tenant(
            tenant_id=tenant_id,
            session_id=session_id,
            query=query,
            limit=limit,
        )
        out: List[EpisodicMemory] = []
        for row in rows:
            try:
                out.append(EpisodicMemory.from_dict(row))
            except (KeyError, TypeError):  # pragma: no cover - defensive
                continue
        return out

    def clear_session(self, *, tenant_id: Optional[str], session_id: str) -> None:
        self._backend.memory_clear_session(
            tenant_id=tenant_id, session_id=session_id
        )

    # -- serialización para el system prompt --------------------------------
    @staticmethod
    def format_as_context(memories: Sequence[EpisodicMemory]) -> str:
        if not memories:
            return ""
        lines: List[str] = []
        for m in memories:
            content = m.content
            if isinstance(content, (list, dict)):  # multimodal/structured
                import json

                try:
                    content = json.dumps(content, ensure_ascii=False)
                except (TypeError, ValueError):  # pragma: no cover
                    content = str(content)
            elif not isinstance(content, str):
                content = str(content)
            lines.append(f"[{m.role}] {content}")
        return "\n".join(lines)

    def as_context(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        recent: int = 8,
        query: Optional[str] = None,
        search_limit: int = 5,
    ) -> str:
        """Devuelve el texto de memoria para inyectar en el system prompt."""
        memories: List[EpisodicMemory] = list(
            self.get_recent(
                tenant_id=tenant_id, session_id=session_id, limit=recent
            )
        )
        if query:
            memories.extend(
                self.search(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    query=query,
                    limit=search_limit,
                )
            )
        # Dedup por id preservando orden.
        seen = set()
        unique: List[EpisodicMemory] = []
        for m in memories:
            if m.id in seen:
                continue
            seen.add(m.id)
            unique.append(m)
        return self.format_as_context(unique)


__all__ = ["EpisodicMemory", "EpisodicStore", "MemoryConfig"]
