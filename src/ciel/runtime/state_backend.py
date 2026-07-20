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
from datetime import datetime, timezone
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

    # --- memoria episódica (Fase 17, tenant-filtered) ----------------------
    # TODAS las lecturas filtran por tenant_id explícitamente para evitar
    # fuga cross-tenant (el ``search`` genérico NO filtra; no usarlo para memoria).
    @abc.abstractmethod
    def memory_append(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
        value: Any,
    ) -> None:
        ...

    @abc.abstractmethod
    def memory_get(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
    ) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def memory_get_recent(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        limit: int = 8,
    ) -> List[dict]:
        ...

    @abc.abstractmethod
    def memory_search_tenant(
        self,
        *,
        tenant_id: Optional[str],
        session_id: Optional[str],
        query: str,
        limit: int = 5,
    ) -> List[dict]:
        ...

    @abc.abstractmethod
    def memory_clear_session(
        self, *, tenant_id: Optional[str], session_id: str
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
    # --- memoria episódica (Fase 17) ----------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_episodic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            session_id TEXT,
            memory_id TEXT,
            value_json TEXT,
            created_at TEXT,
            UNIQUE(tenant_id, session_id, memory_id)
        );
        """
    )
    if _fts5_available(conn):
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_episodic_fts USING fts5(
                    memory_id,
                    value_json,
                    content='memory_episodic',
                    content_rowid='id',
                    tokenize='trigram'
                );
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS me_ai AFTER INSERT ON memory_episodic BEGIN
                    INSERT INTO memory_episodic_fts(rowid, memory_id, value_json) VALUES (new.id, new.memory_id, new.value_json);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS me_ad AFTER DELETE ON memory_episodic BEGIN
                    INSERT INTO memory_episodic_fts(memory_episodic_fts, rowid, memory_id, value_json) VALUES ('delete', old.id, old.memory_id, old.value_json);
                END;
                """
            )
        except Exception:  # pragma: no cover - FTS5 init best-effort
            pass
    conn.commit()
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

    # --- memoria episódica (Fase 17, tenant-filtered) ----------------------
    def memory_append(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
        value: Any,
    ) -> None:
        tenant_value = self._sentinel(tenant_id)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO memory_episodic (tenant_id, session_id, memory_id, value_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, session_id, memory_id) DO UPDATE SET value_json = excluded.value_json, created_at = excluded.created_at
            """,
            (tenant_value, session_id, memory_id, self._dump(value), now),
        )
        self.conn.commit()

    def memory_get(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
    ) -> Optional[dict]:
        tenant_value = self._sentinel(tenant_id)
        row = self.conn.execute(
            "SELECT value_json FROM memory_episodic WHERE tenant_id = ? AND session_id = ? AND memory_id = ?",
            (tenant_value, session_id, memory_id),
        ).fetchone()
        if row is None:
            return None
        return self._normalize_row(row["value_json"])

    def memory_get_recent(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        limit: int = 8,
    ) -> List[dict]:
        tenant_value = self._sentinel(tenant_id)
        rows = self.conn.execute(
            """
            SELECT value_json FROM memory_episodic
            WHERE tenant_id = ? AND session_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (tenant_value, session_id, limit),
        ).fetchall()
        out: List[dict] = []
        for row in rows:
            parsed = self._normalize_row(row["value_json"])
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def memory_search_tenant(
        self,
        *,
        tenant_id: Optional[str],
        session_id: Optional[str],
        query: str,
        limit: int = 5,
    ) -> List[dict]:
        tenant_value = self._sentinel(tenant_id)
        # Búsqueda por substring (LIKE) filtrada ESTRICTAMENTE por tenant_id
        # (riesgo de fuga cross-tenant mitigado). No depende del tokenizer FTS5,
        # así que funciona siempre (offline-safe) y es determinista.
        # El value_json guarda el contenido con escape JSON (p.ej. la ñ como
        # \u00f1), por eso normalizamos la query al mismo formato que produce
        # json.dumps para que el LIKE coincida con caracteres no-ASCII.
        import json as _json

        # El value_json guarda el contenido con escape JSON (p.ej. la ñ como
        # \u00f1), por eso normalizamos la query al mismo formato que produce
        # json.dumps. Escapamos los metacaracteres de LIKE (% _ \) para que la
        # búsqueda sea literal y segura (sin usar ESCAPE, que interferiría con
        # la barra invertida del escape JSON).
        raw = _json.dumps(query).strip(chr(34))
        # Escapamos solo los metacaracteres de LIKE (% _) para que la búsqueda
        # sea literal. NO escapamos la barra invertida: el valor JSON almacena
        # \u00f1 con una barra literal y, sin cláusula ESCAPE, LIKE trata la
        # barra como carácter normal (coincide con el valor almacenado).
        escaped = raw.replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        try:
            if session_id is not None:
                rows = self.conn.execute(
                    """
                    SELECT value_json FROM memory_episodic
                    WHERE tenant_id = ? AND session_id = ? AND value_json LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (tenant_value, session_id, like, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT value_json FROM memory_episodic
                    WHERE tenant_id = ? AND value_json LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (tenant_value, like, limit),
                ).fetchall()
        except Exception:  # query/SQL inesperado => degrada a [].
            return []
        out: List[dict] = []
        for row in rows:
            parsed = self._normalize_row(row["value_json"])
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def memory_clear_session(
        self, *, tenant_id: Optional[str], session_id: str
    ) -> None:
        tenant_value = self._sentinel(tenant_id)
        self.conn.execute(
            "DELETE FROM memory_episodic WHERE tenant_id = ? AND session_id = ?",
            (tenant_value, session_id),
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
        self._memory_episodic = Table(
            "memory_episodic",
            self._meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("tenant_id", String(255)),
            Column("session_id", String(255), nullable=False),
            Column("memory_id", String(1024), nullable=False),
            Column("value_json", Text),
            Column("created_at", String(64)),
            Column(
                "UNIQUE",
                "tenant_id",
                "session_id",
                "memory_id",
                _name="uq_memep_tsm",
            ),
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

    # --- memoria episódica (Fase 17, tenant-filtered) ----------------------
    def memory_append(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
        value: Any,
    ) -> None:
        from datetime import datetime, timezone

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        now = datetime.now(timezone.utc).isoformat()
        tenant_value = self._sentinel_str(tenant_id)
        stmt = pg_insert(self._memory_episodic).values(
            tenant_id=tenant_value,
            session_id=session_id,
            memory_id=memory_id,
            value_json=self._dump(value),
            created_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "session_id", "memory_id"],
            set_={
                "value_json": stmt.excluded.value_json,
                "created_at": stmt.excluded.created_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def memory_get(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        memory_id: str,
    ) -> Optional[dict]:
        from sqlalchemy import select

        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self._memory_episodic.c.value_json).where(
                    self._memory_episodic.c.tenant_id == tenant_value,
                    self._memory_episodic.c.session_id == session_id,
                    self._memory_episodic.c.memory_id == memory_id,
                )
            ).fetchone()
        if row is None:
            return None
        return self._normalize_row(row[0])

    def memory_get_recent(
        self,
        *,
        tenant_id: Optional[str],
        session_id: str,
        limit: int = 8,
    ) -> List[dict]:
        from sqlalchemy import select

        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(self._memory_episodic.c.value_json)
                .where(
                    self._memory_episodic.c.tenant_id == tenant_value,
                    self._memory_episodic.c.session_id == session_id,
                )
                .order_by(self._memory_episodic.c.id.desc())
                .limit(limit)
            ).fetchall()
        out: List[dict] = []
        for row in rows:
            parsed = self._normalize_row(row[0])
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def memory_search_tenant(
        self,
        *,
        tenant_id: Optional[str],
        session_id: Optional[str],
        query: str,
        limit: int = 5,
    ) -> List[dict]:
        from sqlalchemy import select

        like = f"%{query}%"
        tenant_value = self._sentinel_str(tenant_id)
        conds = [
            self._memory_episodic.c.tenant_id == tenant_value,
            self._memory_episodic.c.value_json.ilike(like),
        ]
        if session_id is not None:
            conds.append(self._memory_episodic.c.session_id == session_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(self._memory_episodic.c.value_json)
                .where(*conds)
                .limit(limit)
            ).fetchall()
        out: List[dict] = []
        for row in rows:
            parsed = self._normalize_row(row[0])
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def memory_clear_session(
        self, *, tenant_id: Optional[str], session_id: str
    ) -> None:
        from sqlalchemy import delete

        tenant_value = self._sentinel_str(tenant_id)
        with self.engine.begin() as conn:
            conn.execute(
                delete(self._memory_episodic).where(
                    self._memory_episodic.c.tenant_id == tenant_value,
                    self._memory_episodic.c.session_id == session_id,
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
