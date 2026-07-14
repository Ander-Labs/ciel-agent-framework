from __future__ import annotations

import os

import pytest

from ciel.orchestration.board import BoardTask, KanbanBoard
from ciel.orchestration.queue import DurableQueue, Task


def test_queue_enqueue_dequeue_mark():
    path = os.path.abspath("ciel_queue.sqlite3")
    try:
        os.remove(path)
    except OSError:
        pass
    queue = DurableQueue()
    task = queue.enqueue(Task(kind="job", payload={"a": 1}))
    assert task.id
    pending = queue.dequeue()
    assert pending is not None
    assert pending.id == task.id
    queue.mark(pending.id, "done", result={"ok": True})
    tasks = queue.list_tasks()
    assert any(item.status == "done" for item in tasks)


def test_board_task_lifecycle():
    board = KanbanBoard()
    task = board.add_task(BoardTask(id="t1", title="Test"))
    assert board.show("t1").title == "Test"
    moved = board.move("t1", "in_progress")
    assert moved.status == "in_progress"
    assigned = board.assign("t1", "agent-1")
    assert assigned.assignee == "agent-1"
    assert board.list_tasks(assignee="agent-1") == [task]


def test_board_list_filters():
    board = KanbanBoard()
    task_a = board.add_task(BoardTask(id="a", title="A", status="todo", tenant_id="t1"))
    board.add_task(BoardTask(id="b", title="B", status="todo", tenant_id="t2"))
    assert board.list_tasks(status="todo", tenant_id="t1") == [task_a]
