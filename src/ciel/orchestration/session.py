from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ciel.runtime.memory import MemoryStore


# Fase 5 (cierre) — Session state persistente por tenant entre turnos,
# estilo ADK.sub_agents + sesión durable.
#
# ``SessionStore`` persiste el estado de una session por ``(tenant_id,
# session_id)`` sobre ``MemoryStore`` (multitenancy nativo: ``tenant_id=None``
# ya se normaliza a ``"__none__"`` en ``MemoryStore.set/get``). Esto permite
# que un agente (p.ej. el ``RootAgent``) recuerde el contexto de turnos
# previos al reanudar en un proceso distinto (OFFLINE-SAFE: sin red ni
# proveedor).
#
# Integración con el resto del framework:
#   * ``RootRunner.route`` acepta ``session_store`` + ``session_id`` +
#     ``tenant_id`` y acumula el historial de turnos entre llamadas.
#   * ``SessionStore`` puede vincular la session con tareas del ``KanbanBoard``
#     (mismo ``tenant_id``), cumpliendo el criterio "integrado a board+session".

SESSION_VERSION = 1


class SessionError(Exception):
    pass


class SessionStore:
    """Estado de session durable por tenant, sobre ``MemoryStore``.

    Claves internas (todas namespaced con ``session:`` para no colisionar con
    otros módulos que usan el mismo ``MemoryStore``):

    * ``session:<sid>:turns``      -> {"version", "turns": [turn, ...]}
    * ``session:<sid>:state``      -> {key: value}  (estado arbitrario)
    * ``session:<sid>:board_links``-> {"links": [board_task_id, ...]}
    * ``session_index:<tenant>``   -> {"sessions": [sid, ...]}  (índice)
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    # -- keys ---------------------------------------------------------------
    @staticmethod
    def _turns_key(session_id: str) -> str:
        return f"session:{session_id}:turns"

    @staticmethod
    def _state_key(session_id: str) -> str:
        return f"session:{session_id}:state"

    @staticmethod
    def _links_key(session_id: str) -> str:
        return f"session:{session_id}:board_links"

    @staticmethod
    def _index_key(tenant_id: Optional[str]) -> str:
        sentinel = tenant_id if tenant_id is not None else "__none__"
        return f"session_index:{sentinel}"

    # -- index --------------------------------------------------------------
    def _load_index(self, tenant_id: Optional[str]) -> List[str]:
        # El índice se guarda con session_id == tenant_id (determinista) para
        # no depender de una session concreta.
        sid = tenant_id if tenant_id is not None else "__none__"
        payload = self.memory.get(
            tenant_id=tenant_id, session_id=sid, key=self._index_key(tenant_id)
        )
        if isinstance(payload, dict):
            return list(payload.get("sessions", []))
        return []

    def _register(self, *, tenant_id: Optional[str], session_id: str) -> None:
        sessions = self._load_index(tenant_id)
        if session_id not in sessions:
            sessions.append(session_id)
            sid = tenant_id if tenant_id is not None else "__none__"
            self.memory.set(
                tenant_id=tenant_id,
                session_id=sid,
                key=self._index_key(tenant_id),
                value={"sessions": sessions},
            )

    # -- turns --------------------------------------------------------------
    def append_turn(
        self, *, tenant_id: Optional[str], session_id: str, turn: Dict[str, Any]
    ) -> None:
        """Añade un turno al historial de la session y lo registra en el índice."""
        turn = dict(turn)
        turn.setdefault("ts", time.time())
        turns = self.history(tenant_id=tenant_id, session_id=session_id)
        turns.append(turn)
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id,
            key=self._turns_key(session_id),
            value={"version": SESSION_VERSION, "turns": turns},
        )
        self._register(tenant_id=tenant_id, session_id=session_id)

    def history(self, *, tenant_id: Optional[str], session_id: str) -> List[Dict[str, Any]]:
        """Recupera el historial de turnos (vacío si la session no existe)."""
        payload = self.memory.get(
            tenant_id=tenant_id, session_id=session_id, key=self._turns_key(session_id)
        )
        if isinstance(payload, dict):
            return [dict(t) for t in payload.get("turns", [])]
        return []

    # -- arbitrary state ----------------------------------------------------
    def _load_state_blob(self, tenant_id: Optional[str], session_id: str) -> Dict[str, Any]:
        payload = self.memory.get(
            tenant_id=tenant_id, session_id=session_id, key=self._state_key(session_id)
        )
        return dict(payload) if isinstance(payload, dict) else {}

    def save_state(
        self, *, tenant_id: Optional[str], session_id: str, key: str, value: Any
    ) -> None:
        state = self._load_state_blob(tenant_id, session_id)
        state[key] = value
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id,
            key=self._state_key(session_id),
            value=state,
        )
        self._register(tenant_id=tenant_id, session_id=session_id)

    def load_state(
        self, *, tenant_id: Optional[str], session_id: str, key: str, default: Any = None
    ) -> Any:
        state = self._load_state_blob(tenant_id, session_id)
        return state.get(key, default)

    # -- board integration --------------------------------------------------
    def link_board_task(
        self, *, tenant_id: Optional[str], session_id: str, board_task_id: str
    ) -> None:
        """Vincula una tarea del board (mismo tenant) con la session."""
        links = self.board_links(tenant_id=tenant_id, session_id=session_id)
        if board_task_id not in links:
            links.append(board_task_id)
            self.memory.set(
                tenant_id=tenant_id,
                session_id=session_id,
                key=self._links_key(session_id),
                value={"links": links},
            )

    def board_links(self, *, tenant_id: Optional[str], session_id: str) -> List[str]:
        payload = self.memory.get(
            tenant_id=tenant_id, session_id=session_id, key=self._links_key(session_id)
        )
        if isinstance(payload, dict):
            return list(payload.get("links", []))
        return []

    # -- listing ------------------------------------------------------------
    def list_sessions(self, *, tenant_id: Optional[str]) -> List[str]:
        """Lista los ids de session registrados para un tenant."""
        return self._load_index(tenant_id)


__all__ = ["SessionStore", "SessionError"]
