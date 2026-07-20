"""Integración aditiva de memoria episódica con ``ciel.Agent`` (Pilar A/D1).

IGUAL que ``skill_agent_integration`` para skills: NO reescribe ``api.py``.
Se invoca ``install_agent_memory_support(Agent)`` al final de ``ciel/api.py``
y engancha:

* ``Agent(memory=EpisodicStore, memory_config=MemoryConfig)`` — store opcional.
* Recuperación + inyección en el system prompt en ``_build_request`` (pre-LLM).
* Persistencia automática de user/assistant tras cada ``run``/``arun``.
* Degrada graceful a "sin memoria" si no se configuró (offline-safe).

Aislamiento por ``tenant_id``: la memoria se recupera/persiste SIEMPRE con el
tenant efectivo del run.
"""

from __future__ import annotations

import functools
import uuid
from typing import Any, Optional

from ciel.runtime.memory_episodic import EpisodicStore, MemoryConfig


class AgentMemory:
    """State holder de memoria para un ``Agent`` (aditivo, no invasivo)."""

    def __init__(
        self,
        store: Optional[EpisodicStore],
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self.store = store
        self.config = config or MemoryConfig()
        # session_id por agente; se renueva en cada run si el caller no lo da.
        self._session_id: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self.store is not None

    def session_id(self, *, extra_session_id: Optional[str] = None) -> str:
        if extra_session_id:
            self._session_id = extra_session_id
        elif self._session_id is None:
            self._session_id = str(uuid.uuid4())
        return self._session_id

    def recall_context(
        self, *, tenant_id: Optional[str], session_id: str, prompt: str
    ) -> Optional[str]:
        if not self.enabled:
            return None
        return self.store.as_context(
            tenant_id=tenant_id,
            session_id=session_id,
            recent=self.config.recent_turns,
            query=prompt if self.config.search_limit else None,
            search_limit=self.config.search_limit,
        )

    def persist(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        role: str,
        content: Any,
    ) -> None:
        if not self.enabled:
            return
        try:
            self.store.append(
                tenant_id=tenant_id,
                session_id=session_id,
                role=role,
                content=content,
            )
        except Exception:  # pragma: no cover - memoria nunca debe romper el run
            pass


def install_agent_memory_support(agent_cls: Any) -> Any:
    """Engancha ``memory=`` / ``memory_config=`` en ``Agent`` sin reescribir api.py."""
    original_init = agent_cls.__init__

    @functools.wraps(original_init)
    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        memory_store = kwargs.pop("memory", None)
        memory_config = kwargs.pop("memory_config", None)
        original_init(self, *args, **kwargs)
        self._memory = AgentMemory(memory_store, memory_config)

    agent_cls.__init__ = _patched_init  # type: ignore[assignment]

    # Métodos auxiliares para el runtime (usados por _build_request / arun).
    def _recall(self: Any, prompt: str, tenant_id: Optional[str], session_id: str) -> Optional[str]:
        return self._memory.recall_context(
            tenant_id=tenant_id, session_id=session_id, prompt=prompt
        )

    def _persist(self: Any, tenant_id: Optional[str], session_id: str, role: str, content: Any) -> None:
        self._memory.persist(
            tenant_id=tenant_id, session_id=session_id, role=role, content=content
        )

    agent_cls._memory_recall = _recall  # type: ignore[attr-defined]
    agent_cls._memory_persist = _persist  # type: ignore[attr-defined]
    agent_cls.memory = property(lambda self: self._memory.store)  # type: ignore[attr-defined]
    return agent_cls


__all__ = ["AgentMemory", "install_agent_memory_support"]
