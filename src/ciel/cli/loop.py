from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration.agent import (
    AutonomousAgent,
    EventLoop,
    EventLoopCheckpointStore,
    Task,
)
from ciel.orchestration.supervisor import Supervisor
from ciel.runtime.memory import MemoryStore

console = Console()
loop_app = typer.Typer(name="loop", help="Autonomous event-loop agent (offline-safe)")

DEFAULT_DB_NAME = "ciel_loop.sqlite3"


def resolve_db_path(db_flag: Optional[Path]) -> str:
    """Resuelve la ruta del loop SQLite.

    Prioridad: ``--db`` > variable de entorno ``CIEL_LOOP_DB`` > archivo por
    defecto en el directorio actual.
    """
    if db_flag is not None:
        return str(db_flag)
    env = os.environ.get("CIEL_LOOP_DB")
    if env:
        return env
    return str(Path.cwd() / DEFAULT_DB_NAME)


def _demo_handler(task: Task):
    """Handler OFFLINE: devuelve echo del objetivo, sin red ni proveedor."""

    def _run(t: Task):
        return {"echo": t.goal, "payload": dict(t.payload)}

    return _run


def _print_task(task: Task, title: str = "Task") -> None:
    table = Table(title=title)
    table.add_column("id")
    table.add_column("goal")
    table.add_column("status")
    table.add_column("attempts")
    table.add_column("result")
    table.add_column("error")
    table.add_row(
        task.id[:8],
        task.goal,
        task.status,
        str(task.attempts),
        repr(task.result),
        task.error or "(none)",
    )
    console.print(table)


@loop_app.command("run")
def run(
    goal: str = typer.Argument(..., help="Goal for the autonomous agent"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Explicit run id (for later resume)"),
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite db for the checkpointer (or CIEL_LOOP_DB)"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
    session: Optional[str] = typer.Option(None, "--session-id", help="Session id (for session state)"),
) -> None:
    """Run an autonomous agent over a goal offline (no network, no provider).

    With --db the run is persisted via a checkpointer so it can be resumed
    later with the `resume` command (e.g. after a process restart).
    """
    checkpointer = None
    memory = None
    db_path = None
    if db is not None:
        db_path = resolve_db_path(db)
        memory = MemoryStore(db_path)
        checkpointer = EventLoopCheckpointStore(memory)

    task = Task(goal=goal)
    loop = EventLoop(
        supervisor=Supervisor(),
        checkpointer=checkpointer,
        tenant_id=tenant,
        session_id=session or run_id,
        max_attempts=5,
    )

    async def _run() -> Task:
        return await loop.run(task, _demo_handler(task), run_id=run_id)

    try:
        out = asyncio.run(_run())
    except Exception as exc:
        console.print(f"[red]loop failed:[/] {exc}")
        raise typer.Exit(1)
    finally:
        if memory is not None:
            memory.close()

    _print_task(out, title="Autonomous task")
    if db_path is not None:
        console.print(
            Panel.fit(
                f"run_id: {loop.run_id}\ncheckpointer: {db_path}\n"
                f"tenant: {tenant or '(none)'}\nsession: {session or loop.run_id}\n\n"
                "Resume after a restart with: ciel loop resume --run-id <run_id> --db <db> [--tenant <tenant>]",
                title="Run summary",
                border_style="blue",
            )
        )
    else:
        console.print(
            Panel.fit(
                "Offline demo (no --db): a single autonomous task runs with a local\n"
                "echo handler. No provider, no network required. Pass --db to enable resume.",
                title="Summary",
                border_style="blue",
            )
        )


@loop_app.command("resume")
def resume(
    run_id: str = typer.Option(..., "--run-id", help="Run id to resume"),
    db: Path = typer.Option(..., "--db", help="Same SQLite db used in run"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
    session: Optional[str] = typer.Option(None, "--session-id", help="Session id"),
) -> None:
    """Resume an interrupted autonomous loop from its last checkpoint (requires --db)."""
    db_path = resolve_db_path(db)
    memory = MemoryStore(db_path)
    checkpointer = EventLoopCheckpointStore(memory)

    # Reconstruye el handler offline (determinista por objetivo persistido).
    saved = checkpointer.load(run_id=run_id, tenant_id=tenant, session_id=session or run_id)
    if saved is None:
        console.print(f"[red]no checkpoint found for run_id '{run_id}'[/]")
        memory.close()
        raise typer.Exit(1)
    task = Task.from_snapshot(saved["task"])
    loop = EventLoop(
        supervisor=Supervisor(),
        checkpointer=checkpointer,
        tenant_id=tenant,
        session_id=session or run_id,
        max_attempts=5,
    )

    async def _resume() -> Task:
        return await loop.resume(run_id=run_id, handler=_demo_handler(task))

    try:
        out = asyncio.run(_resume())
    except Exception as exc:
        console.print(f"[red]resume failed:[/] {exc}")
        raise typer.Exit(1)
    finally:
        memory.close()

    _print_task(out, title="Resumed task")
    console.print(
        Panel.fit(
            f"run_id: {run_id}\ncheckpointer: {db_path}\ntenant: {tenant or '(none)'}",
            title="Resume summary",
            border_style="blue",
        )
    )


__all__ = ["loop_app", "run", "resume"]


if __name__ == "__main__":
    loop_app()
