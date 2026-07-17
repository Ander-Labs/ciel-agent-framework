from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ciel.runtime.state_backend import (
    SqliteStateBackend,
    _fts5_available,
    init_schema,
)


@dataclass
class MemoryEntry:
    tenant_id: Optional[str]
    session_id: str
    key: str
    value: Any = None
    value_json: str = "null"


class MemoryStore(SqliteStateBackend):
    """Alias retrocompatible a :class:`SqliteStateBackend` (SQLite en disco).

    ``MemoryStore`` es SQLite en disco desde F5 — el nombre engaña. Para
    F15 se refactorizó para heredar de ``StateBackend`` de modo que cualquier
    store que hoy recibe un ``MemoryStore`` puede recibir también un
    ``PostgresStateBackend`` compartido sin cambios de API.

    Se sigue construyendo con la misma firma: ``MemoryStore(db_path)``.
    """

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)


__all__ = ["MemoryStore", "MemoryEntry", "init_schema", "_fts5_available"]
