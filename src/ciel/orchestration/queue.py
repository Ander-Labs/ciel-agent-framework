from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from uuid import uuid4


DB_PATH = Path("ciel_queue.sqlite3")


def _init_db(path: Path = DB_PATH) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            tenant_id TEXT,
            agent_id TEXT,
            result TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


@dataclass
class Task:
    kind: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    attempts: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DurableQueue:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.conn = _init_db(path)

    def enqueue(self, task: Task) -> Task:
        self.conn.execute(
            "INSERT INTO tasks (id, kind, status, payload, tenant_id, agent_id, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.kind,
                task.status,
                json.dumps(task.payload),
                task.tenant_id,
                task.agent_id,
                task.attempts,
                task.created_at,
                task.updated_at,
            ),
        )
        self.conn.commit()
        return task

    def dequeue(self, status: str = "pending") -> Optional[Task]:
        row = self.conn.execute(
            "SELECT id, kind, status, payload, tenant_id, agent_id, attempts, created_at, updated_at FROM tasks WHERE status = ? ORDER BY created_at LIMIT 1",
            (status,),
        ).fetchone()
        if not row:
            return None
        id_, kind, status_, payload, tenant_id, agent_id, attempts, created_at, updated_at = row
        return Task(
            id=id_,
            kind=kind,
            payload=json.loads(payload),
            status=status_,
            tenant_id=tenant_id,
            agent_id=agent_id,
            attempts=attempts,
            created_at=created_at,
            updated_at=updated_at,
        )

    def mark(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE tasks SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?",
            (
                status,
                json.dumps(result) if result is not None else None,
                error,
                now,
                task_id,
            ),
        )
        self.conn.commit()

    def list_tasks(self, status: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Task]:
        query = "SELECT id, kind, status, payload, tenant_id, agent_id, attempts, created_at, updated_at FROM tasks"
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(query, tuple(params)).fetchall()
        out: List[Task] = []
        for row in rows:
            id_, kind, status_, payload, tenant_id, agent_id, attempts, created_at, updated_at = row
            out.append(
                Task(
                    id=id_,
                    kind=kind,
                    payload=json.loads(payload),
                    status=status_,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    attempts=attempts,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        return out
