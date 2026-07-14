"""CLI `ciel rbac` — gestión de roles y permisos (offline-safe, demo en memoria).

Comandos:
  ciel rbac list-roles                 # imprime roles y permisos por defecto
  ciel rbac assign --subject X --role admin [--tenant T]
  ciel rbac check  --subject X --action agent:run [--tenant T]
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ciel.enterprise.rbac import DEFAULT_ROLES, RBACEngine, RBACError

rbac_app = typer.Typer(name="rbac", help="RBAC roles and permissions")
console = Console()


@rbac_app.command("list-roles")
def list_roles() -> None:
    """List built-in roles and their permissions."""
    table = Table(title="RBAC roles")
    table.add_column("role")
    table.add_column("permissions")
    for name in sorted(DEFAULT_ROLES):
        role = DEFAULT_ROLES[name]
        table.add_row(name, ", ".join(sorted(role.permissions)))
    console.print(table)


@rbac_app.command("assign")
def assign(
    subject: str = typer.Option(..., "--subject", help="Subject (user/service)"),
    role: str = typer.Option(..., "--role", help="Role name"),
    tenant: str | None = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Assign a role to a subject (demo in-memory engine)."""
    engine = RBACEngine()
    try:
        engine.assign(subject, role, tenant_id=tenant)
    except RBACError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=1)
    effective = tenant or "*"
    console.print(f"[green]assigned[/] role={role} subject={subject} tenant={effective}")


@rbac_app.command("check")
def check(
    subject: str = typer.Option(..., "--subject", help="Subject (user/service)"),
    action: str = typer.Option(..., "--action", help="Action, e.g. agent:run"),
    tenant: str | None = typer.Option(None, "--tenant", help="Tenant id"),
) -> None:
    """Check whether a subject may perform an action (demo in-memory engine)."""
    engine = RBACEngine()
    allowed = engine.has_permission(subject, action, tenant_id=tenant)
    role = engine.role_of(subject, tenant_id=tenant)
    if allowed:
        console.print(f"[green]ALLOW[/] {subject} -> {action} (role={role})")
    else:
        console.print(f"[red]DENY[/] {subject} -> {action} (role={role})")
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    rbac_app()
