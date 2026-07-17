"""Subcomando ``ciel studio`` (Fase 13 / F19 — Ciel Studio).

Muestra en consola el snapshot del dashboard de observabilidad (sesiones,
loops y estado) leído del ``StudioStore`` singleton. Offline-safe: no
requiere red. Pensado para inspección rápida junto a ``ciel serve``
(que expone el mismo snapshot en ``GET /v1/studio``).
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.studio import get_studio_store

studio_app = typer.Typer(
    name="studio",
    help="Ciel Studio — dashboard de observabilidad (sesiones/loops).",
    no_args_is_help=True,
)
console = Console()


@studio_app.command("show")
def show(
    tenant: str = typer.Option(None, "--tenant", "-t", help="Filtrar por tenant_id."),
) -> None:
    """Muestra el snapshot actual de sesiones y loops."""
    store = get_studio_store()
    snap = store.snapshot(tenant_id=tenant)

    counts = snap["counts"]
    console.print(
        Panel.fit(
            f"[bold]Ciel Studio[/bold] — sesiones:[cyan]{counts['sessions']}[/] "
            f"loops:[cyan]{counts['loops']}[/] "
            f"en ejecución:[cyan]{counts['running_loops']}[/]",
            title="Dashboard",
        )
    )

    if snap["sessions"]:
        t = Table(title="Sesiones", show_lines=False)
        t.add_column("session_id", style="dim")
        t.add_column("tenant")
        t.add_column("agent")
        t.add_column("prompt")
        t.add_column("tools")
        t.add_column("turns")
        for s in snap["sessions"][:20]:
            t.add_row(
                s.get("id", "")[:16],
                s.get("tenant_id", ""),
                s.get("agent", ""),
                (s.get("prompt") or "")[:32],
                str(s.get("tool_calls", 0)),
                str(s.get("turns", 0)),
            )
        console.print(t)
    else:
        console.print("[dim](sin sesiones registradas)[/dim]")

    if snap["loops"]:
        t2 = Table(title="Loops", show_lines=False)
        t2.add_column("loop_id", style="dim")
        t2.add_column("tenant")
        t2.add_column("status")
        t2.add_column("steps")
        t2.add_column("last_event")
        for l in snap["loops"][:20]:
            t2.add_row(
                l.get("id", "")[:16],
                l.get("tenant_id", ""),
                l.get("status", ""),
                str(l.get("steps", 0)),
                (l.get("last_event") or "")[:32],
            )
        console.print(t2)


@studio_app.command("trace")
def trace(
    run_id: str = typer.Argument(None, help="run_id del grafo a inspeccionar."),
    tenant: str = typer.Option(None, "--tenant", "-t", help="Filtrar por tenant_id."),
) -> None:
    """Muestra runs de grafos y su replay (F20). Sin run_id lista los runs."""
    from ciel.studio_trace import get_trace_store

    store = get_trace_store()
    if run_id:
        run = store.get_run(run_id, tenant_id=tenant)
        if run is None:
            console.print(f"[red]run no encontrado:[/red] {run_id}")
            raise typer.Exit(code=1)
        replay = store.replay(run_id)
        console.print(
            Panel.fit(
                f"[bold]Run[/bold] {run_id[:16]} — pasos:[cyan]{len(replay)}[/] "
                f"tenant:[cyan]{run.get('tenant_id', '')}[/]",
                title="Graph Trace / Replay",
            )
        )
        t = Table(title="Replay (step a step)", show_lines=False)
        t.add_column("step")
        t.add_column("paused")
        t.add_column("node")
        for i, st in enumerate(replay):
            t.add_row(str(i), str(st.get("paused", False)), str(st.get("paused_node") or ""))
        console.print(t)
    else:
        runs = store.list_runs(tenant_id=tenant)
        if not runs:
            console.print("[dim](sin runs de grafo registrados)[/dim]")
            return
        t = Table(title="Graph Runs", show_lines=False)
        t.add_column("run_id", style="dim")
        t.add_column("tenant")
        t.add_column("steps")
        for r in runs[:20]:
            t.add_row(r.get("run_id", "")[:16], r.get("tenant_id", ""), str(len(r.get("steps", []))))
        console.print(t)


@studio_app.command("cost")
def cost(
    tenant: str = typer.Option(None, "--tenant", "-t", help="Filtrar por tenant_id."),
) -> None:
    """Muestra el dashboard de costos (F21) leído del CostGovernor."""
    from ciel.studio_cost import get_cost_store

    store = get_cost_store()
    summary = store.summary(tenant_id=tenant)
    console.print(
        Panel.fit(
            f"[bold]Cost[/bold] total:[cyan]${summary.get('total_usd', 0.0):.4f}[/] "
            f"requests:[cyan]{summary.get('requests', 0)}[/] "
            f"tenants:[cyan]{summary.get('tenants', 0)}[/]",
            title="Cost Dashboard",
        )
    )
    by_model = summary.get("by_model", {})
    if by_model:
        t = Table(title="Por modelo", show_lines=False)
        t.add_column("model")
        t.add_column("$")
        for m, usd in sorted(by_model.items(), key=lambda kv: -kv[1]):
            t.add_row(m, f"{usd:.4f}")
        console.print(t)
