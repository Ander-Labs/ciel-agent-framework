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
