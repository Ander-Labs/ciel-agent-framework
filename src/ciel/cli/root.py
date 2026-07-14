from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration import RootAgent, RootRunner, RootState, Specialist
from ciel.orchestration.supervisor import Supervisor
from ciel.runtime.memory import MemoryStore
from ciel.orchestration.session import SessionStore

console = Console()
root_app = typer.Typer(name="root", help="Run the root agent (ADK sub_agents, offline-safe)")


# --------------------------------------------------------------------------- #
# Handlers / router de DEMOSTRACIÓN (OFFLINE-SAFE: funciones locales).
# --------------------------------------------------------------------------- #
def _db_handler(state: RootState) -> str:
    prior = len(state.history)
    return f"db-handled: {state.prompt} (turnos previos en session: {prior})"


def _net_handler(state: RootState) -> str:
    prior = len(state.history)
    return f"net-handled: {state.prompt} (turnos previos en session: {prior})"


def _root_handler(state: RootState) -> str:
    prior = len(state.history)
    return f"root-handled: {state.prompt} (turnos previos en session: {prior})"


def _demo_router(prompt: str):
    p = prompt.lower()
    if any(k in p for k in ("sql", "base de datos", "tabla", "select", "insert", "update", "delete")):
        return "db"
    if any(k in p for k in ("http", "red", "fetch", "url", "api")):
        return "net"
    return None


def _build_demo_agent() -> RootAgent:
    """Root agent de DEMOSTRACIÓN EN MEMORIA con 2 specialists + root handler."""
    return (
        RootAgent(name="root")
        .add_specialist(Specialist("db", _db_handler, "consultas a base de datos"))
        .add_specialist(Specialist("net", _net_handler, "operaciones de red"))
        .set_router(_demo_router)
        .set_root_handler(_root_handler)
    )


def _resolve_session_store(db: Optional[str], tenant: Optional[str]):
    """Resuelve un SessionStore sobre MemoryStore (o None si no hay --db)."""
    if not db:
        return None
    memory = MemoryStore(db)
    return SessionStore(memory)


@root_app.command("route")
def route(
    prompt: str = typer.Argument(..., help="Petición a enrutar por el root agent"),
    db: Optional[str] = typer.Option(
        None, "--db", help="Ruta del MemoryStore SQLite para session state persistente"
    ),
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Id de session (mantiene historial entre turnos)"
    ),
    tenant: Optional[str] = typer.Option(
        None, "--tenant", help="Tenant id (multitenancy nativo)"
    ),
) -> None:
    """Route a prompt through the demo root agent (offline, ADK sub_agents).

    Con ``--db`` + ``--session-id`` el agente recuerda turnos previos entre
    invocaciones (session state persistente por tenant, estilo ADK). Sin red ni
    proveedor.
    """
    effective_tenant = tenant or os.getenv("CIEL_TENANT")
    agent = _build_demo_agent()
    runner: RootRunner = agent.compile()

    session_store = _resolve_session_store(db, effective_tenant)
    sid = session_id or ("demo-session" if session_store is not None else None)

    try:
        state = asyncio.run(
            runner.route(
                prompt,
                session_id=sid,
                session_store=session_store,
                tenant_id=effective_tenant,
            )
        )
    except KeyboardInterrupt:
        raise typer.Exit(0)

    console.print(
        Panel.fit(
            f"prompt: {state.prompt}\n"
            f"route: {state.route or '(root handler)'}\n"
            f"handled_by_root: {state.handled_by_root}\n"
            f"result: {state.result}\n"
            f"turnos en session: {len(state.history)}",
            title="Root agent (offline demo)",
            border_style="blue",
        )
    )
    if sid:
        console.print(
            f"[dim]session_id={sid} tenant={effective_tenant or '(none)'}"
            f" (session state {'persistido en ' + db if session_store else 'en memoria'})[/dim]"
        )
    if not state.route and not state.handled_by_root:
        raise typer.Exit(1)


# Referencia a tempfile/Path para evitar import no usado en algún linter estricto.
_ = (tempfile, Path)


if __name__ == "__main__":
    root_app()
