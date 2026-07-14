from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ciel.orchestration.board import BoardTask, KanbanBoard

console = Console()
board_app = typer.Typer(name="board", help="Manage the durable kanban board")

# Archivo por defecto en el cwd cuando no se pasa --db ni CIEL_BOARD_DB.
DEFAULT_DB_NAME = "ciel_board.sqlite3"


def resolve_db_path(db_flag: Optional[str]) -> Optional[str]:
    """Resuelve la ruta del board SQLite.

    Prioridad: ``--db`` > variable de entorno ``CIEL_BOARD_DB`` > archivo por
    defecto en el directorio actual. Si nada está configurado se devuelve
    ``None`` (board en memoria, comportamiento legacy).
    """
    if db_flag:
        return db_flag
    env = os.environ.get("CIEL_BOARD_DB")
    if env:
        return env
    return str(Path.cwd() / DEFAULT_DB_NAME)


@board_app.command("add")
def add(
    title: str = typer.Argument(..., help="Task title"),
    task_id: Optional[str] = typer.Option(None, "--id", help="Task id"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee"),
    tenant_id: Optional[str] = typer.Option(None, "--tenant-id", help="Tenant id"),
    db: Optional[str] = typer.Option(None, "--db", help="Ruta del board SQLite (o CIEL_BOARD_DB)"),
) -> None:
    with KanbanBoard(path=resolve_db_path(db)) as board:
        task = BoardTask(id=task_id or "", title=title, assignee=assignee, tenant_id=tenant_id)
        board.add_task(task)
        console.print(f"added {task.id}")


@board_app.command("list")
def list_tasks(
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a"),
    tenant_id: Optional[str] = typer.Option(None, "--tenant-id"),
    db: Optional[str] = typer.Option(None, "--db", help="Ruta del board SQLite (o CIEL_BOARD_DB)"),
) -> None:
    with KanbanBoard(path=resolve_db_path(db)) as board:
        items = board.list_tasks(status=status, assignee=assignee, tenant_id=tenant_id)
        if not items:
            console.print("No tasks")
            raise typer.Exit(0)
        table = Table(title="Board")
        table.add_column("id")
        table.add_column("title")
        table.add_column("status")
        table.add_column("assignee")
        table.add_column("tenant_id")
        for item in items:
            table.add_row(item.id, item.title, item.status, item.assignee or "", item.tenant_id or "")
        console.print(table)


@board_app.command("show")
def show(
    task_id: str = typer.Argument(...),
    db: Optional[str] = typer.Option(None, "--db", help="Ruta del board SQLite (o CIEL_BOARD_DB)"),
) -> None:
    with KanbanBoard(path=resolve_db_path(db)) as board:
        task = board.show(task_id)
        if not task:
            console.print(f"not found {task_id}")
            raise typer.Exit(1)
        console.print(f"id: {task.id}")
        console.print(f"title: {task.title}")
        console.print(f"status: {task.status}")
        console.print(f"assignee: {task.assignee or ''}")
        console.print(f"tenant_id: {task.tenant_id or ''}")


@board_app.command("assign")
def assign(
    task_id: str = typer.Argument(...),
    assignee: str = typer.Argument(...),
    db: Optional[str] = typer.Option(None, "--db", help="Ruta del board SQLite (o CIEL_BOARD_DB)"),
) -> None:
    with KanbanBoard(path=resolve_db_path(db)) as board:
        task = board.assign(task_id, assignee)
        if not task:
            console.print(f"not found {task_id}")
            raise typer.Exit(1)
        console.print(f"assigned {task.id} -> {task.assignee}")


__all__ = ["board_app", "add", "list_tasks", "show", "assign"]

if __name__ == "__main__":
    board_app()
