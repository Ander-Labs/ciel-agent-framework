from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration import (
    Flow,
    FlowCheckpointStore,
    FlowRunner,
    FlowState,
)
from ciel.orchestration.supervisor import Supervisor
from ciel.runtime.memory import MemoryStore

console = Console()
flow_app = typer.Typer(name="flow", help="Build and run event-driven flows (offline-safe)")

# Archivo por defecto en el cwd cuando no se pasa --db ni CIEL_FLOW_DB.
DEFAULT_DB_NAME = "ciel_flow.sqlite3"


def resolve_db_path(db_flag: Optional[Path]) -> str:
    """Resuelve la ruta del grafo SQLite.

    Prioridad: ``--db`` > variable de entorno ``CIEL_FLOW_DB`` > archivo por
    defecto en el directorio actual.
    """
    if db_flag is not None:
        return str(db_flag)
    env = os.environ.get("CIEL_FLOW_DB")
    if env:
        return env
    return str(Path.cwd() / DEFAULT_DB_NAME)


def _build_demo_flow() -> Flow:
    """Flow de DEMOSTRACIÓN EN MEMORIA (estilo CrewAI.Flows).

    ingest -> transform -> router {a: branch_a, b: branch_b}

    No usa red ni proveedor; cada paso escribe en ``state.data``. Pensado para
    smoke tests offline.
    """
    flow = Flow(name="demo")

    def ingest(state: FlowState) -> str:
        state.data["items"] = [1, 2, 3]
        return "ingested"

    def transform(state: FlowState) -> str:
        state.data["count"] = len(state.data["items"])
        return "transformed"

    def decide(state: FlowState) -> str:
        return "a" if state.data["items"][0] == 1 else "b"

    def branch_a(state: FlowState) -> str:
        state.data["result"] = "A"
        return "done-a"

    def branch_b(state: FlowState) -> str:
        state.data["result"] = "B"
        return "done-b"

    flow.add_start(ingest)
    flow.add_listen("ingest", transform)
    flow.add_router("transform", decide, {"a": "branch_a", "b": "branch_b"})
    flow.add_branch(branch_a, step_id="branch_a")
    flow.add_branch(branch_b, step_id="branch_b")
    return flow


def _print_state(state: FlowState, title: str = "Flow") -> None:
    """Imprime con Rich el estado resultante del flow."""
    completed = " -> ".join(state.completed) if state.completed else "(none)"
    data_keys = ", ".join(state.data.keys()) if state.data else "(none)"
    table = Table(title=title)
    table.add_column("completed")
    table.add_column("data keys")
    table.add_column("results")
    table.add_column("last_event")
    table.add_row(
        completed,
        data_keys,
        repr(state.results),
        str(state.last_event),
    )
    console.print(table)
    console.print(
        Panel.fit(
            f"completed: {len(state.completed)} step(s)\n"
            f"data keys: {', '.join(state.data.keys()) or '(none)'}\n"
            f"result: {state.data.get('result', '(none)')}\n"
            f"last_event: {state.last_event}",
            title=title,
            border_style="blue",
        )
    )


@flow_app.command("run")
def run(
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Explicit run id (for later resume)"),
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite db for the checkpointer (or CIEL_FLOW_DB)"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Run an in-memory demo flow offline (no network, no provider).

    With --db the run is persisted via a checkpointer so it can be resumed
    later with the `resume` command.
    """
    checkpointer = None
    memory = None
    db_path = None
    if db is not None:
        db_path = resolve_db_path(db)
        memory = MemoryStore(db_path)
        checkpointer = FlowCheckpointStore(memory)

    flow = _build_demo_flow()
    runner = flow.compile(
        supervisor=Supervisor(),
        checkpointer=checkpointer,
        tenant_id=tenant,
    )

    async def _run() -> FlowState:
        return await runner.run(initial_data={}, run_id=run_id)

    try:
        state = asyncio.run(_run())
    except KeyboardInterrupt:
        raise typer.Exit(0)
    finally:
        if memory is not None:
            memory.close()

    _print_state(state, title="Demo flow")
    if db_path is not None:
        console.print(
            Panel.fit(
                f"run_id: {runner.run_id}\ncheckpointer: {db_path}\ntenant: {tenant or '(none)'}\n\n"
                "Resume with: ciel flow resume --run-id <run_id> --db <db> [--tenant <tenant>]",
                title="Run summary",
                border_style="blue",
            )
        )
    else:
        console.print(
            Panel.fit(
                "Offline demo (no --db): ingest -> transform -> router {a,b}.\n"
                "No provider, no network required. Pass --db to enable resume.",
                title="Summary",
                border_style="blue",
            )
        )


@flow_app.command("resume")
def resume(
    run_id: str = typer.Option(..., "--run-id", help="Run id to resume"),
    db: Path = typer.Option(..., "--db", help="Same SQLite db used in run"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Resume an interrupted flow from its last checkpoint (requires --db)."""
    db_path = resolve_db_path(db)
    memory = MemoryStore(db_path)
    checkpointer = FlowCheckpointStore(memory)

    flow = _build_demo_flow()
    runner = flow.compile(
        supervisor=Supervisor(),
        checkpointer=checkpointer,
        tenant_id=tenant,
    )

    async def _resume() -> FlowState:
        return await runner.resume(run_id=run_id)

    try:
        state = asyncio.run(_resume())
    except Exception as exc:
        console.print(f"[red]resume failed:[/] {exc}")
        raise typer.Exit(1)
    finally:
        memory.close()

    _print_state(state, title="Resumed flow")
    console.print(
        Panel.fit(
            f"run_id: {run_id}\ncheckpointer: {db_path}\ntenant: {tenant or '(none)'}",
            title="Resume summary",
            border_style="blue",
        )
    )


__all__ = ["flow_app", "run", "resume"]


if __name__ == "__main__":
    flow_app()
