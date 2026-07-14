from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _fts5_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT * FROM pragma_compile_options WHERE compile_options LIKE '%FTS5%'").fetchone()
    return bool(row)


def init_schema(conn: sqlite3.Connection) -> None:
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
        except sqlite3.OperationalError:
            pass
    conn.commit()


@dataclass
class MemoryEntry:
    tenant_id: Optional[str]
    session_id: str
    key: str
    value: Any = None
    value_json: str = "null"


class MemoryStore:
    def __init__(self, db_path: str) -> None:
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
        # SQLite no trata dos NULL como iguales para UNIQUE, así que un
        # tenant nulo se normaliza a un sentinel para que el upsert
        # (ON CONFLICT) y las búsquedas funcionen de forma determinista.
        tenant_value: Any = tenant_id if tenant_id is not None else "__none__"
        now = datetime.now(timezone.utc).isoformat()
        try:
            value_json = json.dumps(value)
        except TypeError:
            value_json = json.dumps({"repr": repr(value)})
        self.conn.execute(
            """
            INSERT INTO memory (tenant_id, session_id, key, value_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, session_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (tenant_value, session_id, key, value_json, now, now),
        )
        self.conn.commit()

    def get(self, *, tenant_id: Optional[str], session_id: str, key: str) -> Optional[Any]:
        # SQLite no coincide `= NULL`; cuando no hay tenant usamos `IS NULL`
        # y el sentinel de escritura para mantener coherencia con `set`.
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
        return json.loads(row["value_json"])

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
        try:
            arguments_json = json.dumps(arguments)
        except TypeError:
            arguments_json = json.dumps({"repr": repr(arguments)})
        try:
            output_json = json.dumps(output)
        except TypeError:
            output_json = json.dumps({"repr": repr(output)})
        tenant_value = tenant_id if tenant_id is not None else "__none__"
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
                arguments_json,
                output_json,
                error,
                started_at,
                finished_at,
                duration_ms,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
