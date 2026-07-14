from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration import AgentSpec, GraphCheckpointStore, GraphState, StateGraph
from ciel.runtime.memory import MemoryStore

console = Console()
graph_app = typer.Typer(name="graph", help="Build and run explicit state graphs (offline-safe)")

# Archivo por defecto en el cwd cuando no se pasa --db ni CIEL_GRAPH_DB.
DEFAULT_DB_NAME = "ciel_graph.sqlite3"


def resolve_db_path(db_flag: Optional[Path]) -> str:
    """Resuelve la ruta del grafo SQLite.

    Prioridad: ``--db`` > variable de entorno ``CIEL_GRAPH_DB`` > archivo por
    defecto en el directorio actual.
    """
    if db_flag is not None:
        return str(db_flag)
    env = os.environ.get("CIEL_GRAPH_DB")
    if env:
        return env
    return str(Path.cwd() / DEFAULT_DB_NAME)


def _build_demo_graph() -> StateGraph:
    """Grafo de DEMOSTRACIÓN EN MEMORIA: entry -> plan -> execute -> finish.

    No usa red ni proveedor; cada nodo escribe en ``state.data`` y devuelve un
    payload. Pensado para smoke tests offline (igual que ``ciel chat`` con
    ``_EchoProvider``).
    """
    graph = StateGraph(name="demo")

    async def entry(state_data: dict) -> dict:
        state_data.setdefault("started", True)
        return {"node": "entry"}

    async def plan(state_data: dict) -> dict:
        state_data["plan"] = "Define the task and decompose it into steps."
        return {"node": "plan", "plan": state_data["plan"]}

    async def execute(state_data: dict) -> dict:
        state_data["result"] = "Executed the plan and produced the result."
        return {"node": "execute", "result": state_data["result"]}

    async def finish(state_data: dict) -> dict:
        state_data["done"] = True
        return {"node": "finish"}

    graph.add_node("entry", entry)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("finish", finish)
    graph.add_edge("entry", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "finish")
    graph.set_entry_point("entry")
    graph.set_finish_point("finish")
    return graph


def _build_spec_graph(spec: AgentSpec) -> StateGraph:
    """Construye un grafo pipeline lineal a partir de un AgentSpec.

    ``entry`` = ``steps[0].id``, aristas en orden, ``finish`` = último paso.
    Cada nodo guarda en ``state.data[f"__out__{step.id}"]`` un dict con el
    id/kind/prompt del paso.
    """
    graph = StateGraph(name=spec.name or "spec")
    steps = list(spec.steps)
    if not steps:
        raise typer.BadParameter("AgentSpec must have at least one step")

    def _make_fn(step):
        async def _fn(state_data: dict) -> dict:
            payload = {"id": step.id, "kind": step.kind, "prompt": step.prompt}
            state_data[f"__out__{step.id}"] = payload
            return payload

        return _fn

    for step in steps:
        graph.add_node(step.id, _make_fn(step))
    for i in range(len(steps) - 1):
        graph.add_edge(steps[i].id, steps[i + 1].id)
    graph.set_entry_point(steps[0].id)
    graph.set_finish_point(steps[-1].id)
    return graph


def _print_state(state: GraphState, title: str = "Graph") -> None:
    """Imprime con Rich el estado resultante del grafo."""
    visited = " -> ".join(state.visited) if state.visited else "(none)"
    data_keys = ", ".join(state.data.keys()) if state.data else "(none)"
    table = Table(title=title)
    table.add_column("visited")
    table.add_column("data keys")
    table.add_column("current_node")
    table.add_column("last_output")
    table.add_row(
        visited,
        data_keys,
        str(state.current_node),
        repr(state.last_output),
    )
    console.print(table)
    console.print(
        Panel.fit(
            f"visited: {len(state.visited)} node(s)\n"
            f"data keys: {', '.join(state.data.keys()) or '(none)'}\n"
            f"current_node: {state.current_node}",
            title=title,
            border_style="blue",
        )
    )


@graph_app.command("demo")
def demo() -> None:
    """Run an in-memory demo graph offline (no network, no provider)."""
    graph = _build_demo_graph()
    runner = graph.compile()  # Supervisor() por defecto, sin proveedor -> offline-safe

    async def _run() -> GraphState:
        return await runner.run(initial_data={})

    try:
        state = asyncio.run(_run())
    except KeyboardInterrupt:
        raise typer.Exit(0)

    _print_state(state, title="Demo graph")
    console.print(
        Panel.fit(
            "Offline demo: entry -> plan -> execute -> finish.\n"
            "No provider, no network required.",
            title="Summary",
            border_style="blue",
        )
    )


@graph_app.command("run")
def run(
    spec: Optional[Path] = typer.Option(
        None, "--spec", "-s", help="YAML AgentSpec (name, topology, steps[{id,kind,tool,prompt,depends_on}])"
    ),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Explicit run id (for later resume)"),
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite db for the checkpointer (or CIEL_GRAPH_DB)"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Run a graph. With --spec builds a linear pipeline; otherwise runs the demo."""
    db_path = resolve_db_path(db)
    memory = MemoryStore(db_path)
    checkpointer = GraphCheckpointStore(memory)

    if spec is not None:
        agent_spec = AgentSpec.from_yaml(Path(spec).read_text())
        graph = _build_spec_graph(agent_spec)
        label = f"Spec graph: {agent_spec.name}"
    else:
        graph = _build_demo_graph()
        label = "Demo graph (no --spec)"

    runner = graph.compile(checkpointer=checkpointer, tenant_id=tenant)

    async def _run() -> GraphState:
        return await runner.run(initial_data={}, run_id=run_id)

    try:
        state = asyncio.run(_run())
    except KeyboardInterrupt:
        raise typer.Exit(0)
    finally:
        memory.close()

    _print_state(state, title=label)
    console.print(
        Panel.fit(
            f"run_id: {runner.run_id}\ncheckpointer: {db_path}\ntenant: {tenant or '(none)'}",
            title="Run summary",
            border_style="blue",
        )
    )


@graph_app.command("resume")
def resume(
    run_id: str = typer.Option(..., "--run-id", help="Run id to resume"),
    db: Path = typer.Option(..., "--db", help="Same SQLite db used in run"),
    spec: Optional[Path] = typer.Option(
        None, "--spec", "-s", help="YAML AgentSpec used in run (else demo graph)"
    ),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Resume an interrupted graph from its last checkpoint."""
    db_path = resolve_db_path(db)
    memory = MemoryStore(db_path)
    checkpointer = GraphCheckpointStore(memory)

    if spec is not None:
        agent_spec = AgentSpec.from_yaml(Path(spec).read_text())
        graph = _build_spec_graph(agent_spec)
    else:
        graph = _build_demo_graph()

    runner = graph.compile(checkpointer=checkpointer, tenant_id=tenant)

    async def _resume() -> GraphState:
        return await runner.resume(run_id=run_id)

    try:
        state = asyncio.run(_resume())
    except Exception as exc:
        console.print(f"[red]resume failed:[/] {exc}")
        raise typer.Exit(1)
    finally:
        memory.close()

    _print_state(state, title="Resumed graph")


__all__ = ["graph_app", "demo", "run", "resume"]

if __name__ == "__main__":
    graph_app()
