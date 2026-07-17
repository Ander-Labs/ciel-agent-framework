"""State backends compartidos para ``ciel serve`` multi-réplica (Fase 14 / F15).

:class:`StateBackend` es la interfaz mínima que todos los stores de estado
consumen (``CheckpointStore``, ``SessionStore``, ``GraphCheckpointStore``,
``EventLoopCheckpointStore``). Hoy todos reciben un ``MemoryStore`` (que es
SQLite en disco, NO memoria) y usan sólo ``set/get/delete``. Para soportar
N>=2 réplicas detrás de un balanceador, el state debe vivir en un backend
compartido (Postgres en prod, SQLite local en dev).

Decisiones de diseño (F15):
* Offline-safe primero: el default SIEMPRE es SQLite (sin remoto).
* Retrocompatibilidad: ``MemoryStore`` sigue siendo construible con
  ``MemoryStore(path)`` y aceptable donde se espera un ``StateBackend``.
* Upsert idempotente por ``(tenant_id, session_id, key)`` para evitar races
  entre réplicas.
* ``is_ready()`` separa liveness de readiness (lo usa ``/readyz`` en F16).

Los backends implementan la misma superficie que ``MemoryStore`` más
``is_ready``. La FTS (full-text search) sólo existe en SQLite; en Postgres
``search`` hace un ``ILIKE`` best-effort sobre ``value_json``.
"""

from __future__ import annotations

import abc
import json
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------
class StateBackend(abc.ABC):
    """Interfaz mínima de persistencia compartida (multi-réplica)."""

    backend_type: str = "abstract"

    @abc.abstractmethod
    def set(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        key: str,
        value: Any,
    ) -> None:
        ...

    @abc.abstractmethod
    def get(self, *, tenant_id: Optional[str], session_id: str, key: str) -> Optional[Any]:
        ...

    @abc.abstractmethod
    def delete(self, *, tenant_id: Optional[str], session_id: str, key: str) -> None:
        ...

    @abc.abstractmethod
    def search(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def record_tool_execution(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        toolset: str,
        tool_name: str,
        arguments: Any,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        output: Any = None,
        error: Optional[str] = None,
    ) -> None:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...

    # --- readiness (usado por /readyz en F16) ------------------------------
    def is_ready(self) -> bool:
        """Devuelve True si el backend está conectado y migrado.

        El default asume listo; los backends remotos sobrescriben esto con una
        comprobación real de conectividad.
        """
        return True

    # --- utilidades compartidas --------------------------------------------
    @staticmethod
    def _sentinel(tenant_id: Optional[str]) -> Any:
        """SQLite no trata dos NULL como iguales para UNIQUE; normaliza None."""
        return tenant_id if tenant_id is not None else "__none__"

    @staticmethod
    def _dump(value: Any) -> str:
        try:
            return json.dumps(value)
        except TypeError:
            return json.dumps({"repr": repr(value)})

    @staticmethod
    def _normalize_row(value_json: Optional[str]) -> Optional[Any]:
        if value_json is None:
            return None
        try:
            return json.loads(value_json)
        except (TypeError, json.JSONDecodeError):
            return None


# ---------------------------------------------------------------------------
# SQLite (default offline)
# ---------------------------------------------------------------------------
def _fts5_available(conn) -> bool:  # type: ignore[no-untyped-def]
    row = conn.execute(
        "SELECT * FROM pragma_compile_options WHERE compile_options LIKE '%FTS5%'"
    ).fetchone()
    return bool(row)


def init_schema(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            session_id TEXT,
            key TEXT,
            value_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(tenant_id, session_id, key)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            session_id TEXT,
            toolset TEXT,
            tool_name TEXT,
            arguments_json TEXT,
            output_json TEXT,
            error TEXT,
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER
        );
        """
    )
    if _fts5_available(conn):
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    key,
                    value_json,
                    content='memory',
                    content_rowid='id'
                );
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
                    INSERT INTO memory_fts(rowid, key, value_json) VALUES (new.id, new.key, new.value_json);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, key, value_json) VALUES ('delete', old.id, old.key, old.value_json);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, key, value_json) VALUES ('delete', old.id, old.key, old.value_json);
                    INSERT INTO memory_fts(rowid, key, value_json) VALUES (new.id, new.key, new.value_json);
                END;
                """
            )
        except Exception:  # pragma: no cover - FTS5 init best-effort
            pass
    conn.commit()


class SqliteStateBackend(StateBackend):
    """Backend SQLite en disco (default offline). Hereda el esquema de F15-.

    Mantiene FTS5 cuando está disponible; si no, ``search`` degrada a lista
    vacía (comportamiento idéntico al ``MemoryStore`` original).
    """

    backend_type = "sqlite"

    def __init__(self, db_path: str) -> None:
        import sqlite3

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def set(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        key: str,
        value: Any,
    ) -> None:
        tenant_value = self._sentinel(tenant_id)
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        self.conn.execute(
            """
            INSERT INTO memory (tenant_id, session_id, key, value_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, session_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (tenant_value, session_id, key, self._dump(value), now, now),
        )
        self.conn.commit()

    def get(self, *, tenant_id: Optional[str], session_id: str, key: str) -> Optional[Any]:
        import sqlite3

        if tenant_id is None:
            row = self.conn.execute(
                "SELECT value_json FROM memory WHERE tenant_id = ? AND session_id = ? AND key = ?",
                ("__none__", session_id, key),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT value_json FROM memory WHERE tenant_id = ? AND session_id = ? AND key = ?",
                (tenant_id, session_id, key),
            ).fetchone()
        if row is None:
            return None
        return self._normalize_row(row["value_json"])

    def delete(self, *, tenant_id: Optional[str], session_id: str, key: str) -> None:
        if tenant_id is None:
            self.conn.execute(
                "DELETE FROM memory WHERE tenant_id = ? AND session_id = ? AND key = ?",
                ("__none__", session_id, key),
            )
        else:
            self.conn.execute(
                "DELETE FROM memory WHERE tenant_id = ? AND session_id = ? AND key = ?",
                (tenant_id, session_id, key),
            )
        self.conn.commit()

    def search(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        import sqlite3

        try:
            rows = self.conn.execute(
                "SELECT key, value_json FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        results: List[Dict[str, Any]] = []
        for row in rows:
            try:
                results.append({"key": row["key"], "value": json.loads(row["value_json"])})
            except TypeError:
                results.append({"key": row["key"], "value": None})
        return results

    def record_tool_execution(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        toolset: str,
        tool_name: str,
        arguments: Any,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        output: Any = None,
        error: Optional[str] = None,
    ) -> None:
        tenant_value = self._sentinel(tenant_id)
        self.conn.execute(
            """
            INSERT INTO tool_execution_log (tenant_id, session_id, toolset, tool_name, arguments_json, output_json, error, started_at, finished_at, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_value,
                session_id,
                toolset,
                tool_name,
                self._dump(arguments),
                self._dump(output),
                error,
                started_at,
                finished_at,
                duration_ms,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# Postgres (backend de producción, opt-in vía CIEL_STATE_BACKEND=postgres)
# ---------------------------------------------------------------------------
class PostgresStateBackend(StateBackend):
    """Backend Postgres compartido (idempotente entre réplicas).

    Opt-in: ``CIEL_STATE_BACKEND=postgres`` + ``CIEL_STATE_DSN``. Requiere el
    extra ``pg`` (``psycopg[binary]``). Usa SQLAlchemy 2.x core.

    Upsert idempotente por ``(tenant_id, session_id, key)`` con
    ``ON CONFLICT DO UPDATE`` (equivalente al de SQLite) para que dos réplicas
    que escriban la misma clave no generen race corruptor.
    """

    backend_type = "postgres"

    def __init__(self, dsn: str) -> None:
        from sqlalchemy import (
            Column,
            Integer,
            MetaData,
            String,
            Table,
            Text,
            create_engine,
        )
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        self._pg_insert = pg_insert
        self.engine = create_engine(dsn, pool_pre_ping=True, future=True)
        self._meta = MetaData()
        self._memory = Table(
            "memory",
            self._meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("tenant_id", String(255)),
            Column("session_id", String(255), nullable=False),
            Column("key", String(1024), nullable=False),
            Column("value_json", Text),
            Column("created_at", String(64)),
            Column("updated_at", String(64)),
            Column("UNIQUE", "tenant_id", "session_id", "key", _name="uq_memory_tsk"),
        )
        self._tool_log = Table(
            "tool_execution_log",
            self._meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("tenant_id", String(255)),
            Column("session_id", String(255)),
            Column("toolset", String(255)),
            Column("tool_name", String(255)),
            Column("arguments_json", Text),
            Column("output_json", Text),
            Column("error", Text),
            Column("started_at", String(64)),
            Column("finished_at", String(64)),
            Column("duration_ms", Integer),
        )
        self._create_schema()

    def _create_schema(self) -> None:
        from sqlalchemy import inspect

        with self.engine.begin() as conn:
            inspector = inspect(self.engine)
            if not inspector.has_table("memory"):
                self._meta.create_all(conn)

    def _sentinel_str(self, tenant_id: Optional[str]) -> str:
        return tenant_id if tenant_id is not None else "__none__"

    def set(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        key: str,
        value: Any,
    ) -> None:
        from datetime import datetime, timezone

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        now = datetime.now(timezone.utc).isoformat()
        tenant_value = self._sentinel_str(tenant_id)
        stmt = pg_insert(self._memory).values(
            tenant_id=tenant_value,
            session_id=session_id,
            key=key,
            value_json=self._dump(value),
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "session_id", "key"],
            set_={"value_json": stmt.excluded.value_json, "updated_at": stmt.excluded.updated_at},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def get(self, *, tenant_id: Optional[str], session_id: str, key: str) -> Optional[Any]:
        from sqlalchemy import select

        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self._memory.c.value_json).where(
                    self._memory.c.tenant_id == tenant_value,
                    self._memory.c.session_id == session_id,
                    self._memory.c.key == key,
                )
            ).fetchone()
        if row is None:
            return None
        return self._normalize_row(row[0])

    def delete(self, *, tenant_id: Optional[str], session_id: str, key: str) -> None:
        from sqlalchemy import delete

        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.begin() as conn:
            conn.execute(
                delete(self._memory).where(
                    self._memory.c.tenant_id == tenant_value,
                    self._memory.c.session_id == session_id,
                    self._memory.c.key == key,
                )
            )

    def search(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        from sqlalchemy import select

        like = f"%{query}%"
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(self._memory.c.key, self._memory.c.value_json)
                .where(self._memory.c.value_json.ilike(like))
                .limit(limit)
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append({"key": row[0], "value": self._normalize_row(row[1])})
        return results

    def record_tool_execution(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        toolset: str,
        tool_name: str,
        arguments: Any,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        output: Any = None,
        error: Optional[str] = None,
    ) -> None:
        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.begin() as conn:
            conn.execute(
                self._tool_log.insert().values(
                    tenant_id=tenant_value,
                    session_id=session_id,
                    toolset=toolset,
                    tool_name=tool_name,
                    arguments_json=self._dump(arguments),
                    output_json=self._dump(output),
                    error=error,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                )
            )

    def is_ready(self) -> bool:
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # pragma: no cover - depends on live DB
            return False

    def close(self) -> None:
        self.engine.dispose()


# ---------------------------------------------------------------------------
# Factoría (lee CIEL_STATE_BACKEND / CIEL_STATE_DSN)
# ---------------------------------------------------------------------------
def build_state_backend(
    *,
    backend: Optional[str] = None,
    dsn: Optional[str] = None,
    sqlite_path: Optional[str] = None,
) -> StateBackend:
    """Construye el backend de state según entorno.

    Resolución (offline-safe):
    * ``CIEL_STATE_BACKEND=postgres`` (o backend="postgres") -> PostgresStateBackend
      usando ``CIEL_STATE_DSN`` (o dsn=...).
    * Cualquier otro valor (incluido None/"sqlite") -> SqliteStateBackend con
      ``CIEL_STATE_SQLITE`` (o sqlite_path=...) o un archivo temporal por defecto.
    """
    import os
    import tempfile
    from pathlib import Path

    resolved = (backend or os.getenv("CIEL_STATE_BACKEND") or "sqlite").lower()
    if resolved == "postgres":
        pg_dsn = dsn or os.getenv("CIEL_STATE_DSN")
        if not pg_dsn:
            raise RuntimeError(
                "CIEL_STATE_BACKEND=postgres requiere CIEL_STATE_DSN (DSN de Postgres)"
            )
        return PostgresStateBackend(pg_dsn)

    sqlite_file = sqlite_path or os.getenv("CIEL_STATE_SQLITE")
    if not sqlite_file:
        tmp = Path(tempfile.gettempdir()) / "ciel_state.sqlite"
        sqlite_file = str(tmp)
    return SqliteStateBackend(sqlite_file)


__all__ = [
    "StateBackend",
    "SqliteStateBackend",
    "PostgresStateBackend",
    "build_state_backend",
]
