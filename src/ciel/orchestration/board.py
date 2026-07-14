from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class BoardTask:
    def __init__(
        self,
        id: str,
        title: str,
        status: str = "todo",
        assignee: Optional[str] = None,
        tenant_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        self.id = id
        self.title = title
        self.status = status
        self.assignee = assignee
        self.tenant_id = tenant_id
        self.metadata = metadata or {}


class KanbanBoard:
    """In-memory kanban board, optionally backed by a durable SQLite store.

    When ``path`` is ``None`` (the default) the board keeps tasks in a process
    local ``dict`` exactly as before -- this preserves the existing in-memory
    API used by the gateway and the CLI. When ``path`` is provided the board
    transparently reads and writes every task to a SQLite database opened in
    WAL mode, so state survives process restarts.
    """

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = None if path is None else str(path)
        self._tasks: Dict[str, BoardTask] = {}
        self._conn: Optional[sqlite3.Connection] = None
        if self._path is not None:
            self._conn = sqlite3.connect(self._path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS board_tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assignee TEXT,
                    tenant_id TEXT,
                    metadata_json TEXT
                )
                """
            )
            self._conn.commit()

    # -- helpers -------------------------------------------------------------
    def _row_to_task(self, row: sqlite3.Row) -> BoardTask:
        return BoardTask(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            assignee=row["assignee"],
            tenant_id=row["tenant_id"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )

    def _task_to_row(self, task: BoardTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "assignee": task.assignee,
            "tenant_id": task.tenant_id,
            "metadata_json": json.dumps(task.metadata or {}),
        }

    # -- public API ----------------------------------------------------------
    def add_task(self, task: BoardTask) -> BoardTask:
        if self._conn is None:
            self._tasks[task.id] = task
            return task

        row = self._task_to_row(task)
        self._conn.execute(
            """
            INSERT INTO board_tasks (id, title, status, assignee, tenant_id, metadata_json)
            VALUES (:id, :title, :status, :assignee, :tenant_id, :metadata_json)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                status=excluded.status,
                assignee=excluded.assignee,
                tenant_id=excluded.tenant_id,
                metadata_json=excluded.metadata_json
            """,
            row,
        )
        self._conn.commit()
        return task

    def assign(self, task_id: str, assignee: str) -> Optional[BoardTask]:
        if self._conn is None:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.assignee = assignee
            task.status = "in_progress"
            return task

        cur = self._conn.execute(
            """
            UPDATE board_tasks
            SET assignee = ?, status = 'in_progress'
            WHERE id = ?
            """,
            (assignee, task_id),
        )
        if cur.rowcount == 0:
            return None
        self._conn.commit()
        return self.show(task_id)

    def move(self, task_id: str, status: str) -> Optional[BoardTask]:
        if self._conn is None:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.status = status
            return task

        cur = self._conn.execute(
            "UPDATE board_tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        if cur.rowcount == 0:
            return None
        self._conn.commit()
        return self.show(task_id)

    def list_tasks(
        self,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[BoardTask]:
        if self._conn is None:
            out: List[BoardTask] = []
            for task in self._tasks.values():
                if status and task.status != status:
                    continue
                if assignee and task.assignee != assignee:
                    continue
                if tenant_id and task.tenant_id != tenant_id:
                    continue
                out.append(task)
            return out

        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if assignee:
            clauses.append("assignee = ?")
            params.append(assignee)
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            f"SELECT id, title, status, assignee, tenant_id, metadata_json FROM board_tasks{where}",
            params,
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def show(self, task_id: str) -> Optional[BoardTask]:
        if self._conn is None:
            return self._tasks.get(task_id)

        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT id, title, status, assignee, tenant_id, metadata_json FROM board_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def close(self) -> None:
        if self._conn is not None:
            # Flush the WAL back into the main database file so the
            # board.sqlite-wal / board.sqlite-shm side-car files are released
            # (important on Windows where they otherwise stay locked).
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "KanbanBoard":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
