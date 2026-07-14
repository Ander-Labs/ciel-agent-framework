from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ciel.orchestration.board import BoardTask, KanbanBoard


def _make_task(tid: str, tenant: str = "t1") -> BoardTask:
    return BoardTask(
        id=tid,
        title=f"Task {tid}",
        status="todo",
        assignee=None,
        tenant_id=tenant,
        metadata={"priority": "high", "tag": tid},
    )


class _RetryTempDir:
    """Temporary directory whose cleanup tolerates transient Windows file locks.

    Freshly created ``.sqlite`` files can briefly be locked by the OS/antivirus
    after the connection is closed, which makes ``TemporaryDirectory``'s
    ``rmtree`` fail on Windows. We retry the removal a few times with a short
    backoff so the test stays green without weakening the WAL guarantees.
    """

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp())

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc: object) -> None:
        for _ in range(10):
            try:
                shutil.rmtree(self.path)
                return
            except (PermissionError, OSError):
                time.sleep(0.1)
        # Best effort: leave the dir behind rather than fail the test.
        try:
            shutil.rmtree(self.path, ignore_errors=True)
        except Exception:
            pass


def test_sqlite_add_move_assign_and_persist_after_reopen() -> None:
    with _RetryTempDir() as tmp:
        db_path = Path(tmp) / "board.sqlite"

        # First instance: add, move, assign.
        board1 = KanbanBoard(path=db_path)
        board1.add_task(_make_task("a"))
        board1.add_task(_make_task("b", tenant="t2"))
        board1.move("a", "doing")
        board1.assign("a", "alice")

        assert board1.show("a").status == "in_progress"
        assert board1.show("a").assignee == "alice"
        listed_a = board1.list_tasks(tenant_id="t1")
        assert len(listed_a) == 1 and listed_a[0].id == "a"
        board1.close()

        # Reopen the same path: data must survive the restart.
        board2 = KanbanBoard(path=db_path)
        assert board2.show("a") is not None
        assert board2.show("a").status == "in_progress"
        assert board2.show("a").assignee == "alice"
        assert board2.show("a").tenant_id == "t1"
        assert board2.show("a").metadata == {"priority": "high", "tag": "a"}

        # Multi-tenancy filter is a real SQL filter.
        assert [t.id for t in board2.list_tasks(tenant_id="t2")] == ["b"]
        assert [t.id for t in board2.list_tasks()] == ["a", "b"]
        assert [t.id for t in board2.list_tasks(status="in_progress")] == ["a"]
        board2.close()


def test_in_memory_board_keeps_existing_api() -> None:
    board = KanbanBoard()
    t = board.add_task(_make_task("x"))
    assert t.id == "x"
    assert board.show("x") is not None
    board.assign("x", "bob")
    assert board.show("x").status == "in_progress"
    board.move("x", "done")
    assert board.show("x").status == "done"
    assert board.list_tasks(tenant_id="t1") == [board.show("x")]
    assert board.list_tasks(tenant_id="nope") == []
