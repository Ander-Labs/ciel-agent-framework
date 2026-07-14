"""CLI `ciel cost` — cost governance (offline-safe, demo en memoria).

Comandos:
  ciel cost record --tenant T --model gpt-4o --in 1000 --out 500 [--price-in X --price-out Y]
  ciel cost status --tenant T
  ciel cost check  --tenant T --model gpt-4o --in 1000 --out 500
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ciel.enterprise.cost import BudgetExceededError, CostGovernor, ModelCost

cost_app = typer.Typer(name="cost", help="Cost governance per tenant/model")
console = Console()


def _governor() -> CostGovernor:
    return CostGovernor(
        budgets={"*": 10.0},
        models={
            "gpt-4o": ModelCost(per_1k_input=0.005, per_1k_output=0.015),
            "echo": ModelCost(per_1k_input=0.0, per_1k_output=0.0),
        },
    )


@cost_app.command("record")
def record(
    tenant: str = typer.Option(..., "--tenant", help="Tenant id"),
    model: str = typer.Option(..., "--model", help="Model id"),
    input_tokens: int = typer.Option(..., "--in", help="Input tokens"),
    output_tokens: int = typer.Option(..., "--out", help="Output tokens"),
    price_in: float = typer.Option(0.005, "--price-in", help="$/1k input"),
    price_out: float = typer.Option(0.015, "--price-out", help="$/1k output"),
) -> None:
    """Record a usage and print the running spend for the tenant."""
    gov = _governor()
    gov.models[model] = ModelCost(per_1k_input=price_in, per_1k_output=price_out)
    spent = gov.record(tenant, model, input_tokens, output_tokens)
    console.print(
        f"[green]recorded[/] tenant={tenant} model={model} "
        f"spent=${spent:.4f} remaining=${gov.remaining(tenant):.4f}"
    )


@cost_app.command("status")
def status(tenant: str = typer.Option(..., "--tenant", help="Tenant id")) -> None:
    """Show current spend / budget / remaining for a tenant."""
    gov = _governor()
    table = Table(title=f"Cost status — {tenant}")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("spent", f"${gov.spent(tenant):.4f}")
    table.add_row("budget", f"${gov.budget_of(tenant):.4f}")
    table.add_row("remaining", f"${gov.remaining(tenant):.4f}")
    table.add_row("alerted", str(gov.alerted(tenant)))
    console.print(table)


@cost_app.command("check")
def check(
    tenant: str = typer.Option(..., "--tenant", help="Tenant id"),
    model: str = typer.Option(..., "--model", help="Model id"),
    input_tokens: int = typer.Option(..., "--in", help="Input tokens"),
    output_tokens: int = typer.Option(..., "--out", help="Output tokens"),
    price_in: float = typer.Option(0.005, "--price-in", help="$/1k input"),
    price_out: float = typer.Option(0.015, "--price-out", help="$/1k output"),
) -> None:
    """Check whether a planned usage is within budget (exit 1 if denied)."""
    gov = _governor()
    gov.models[model] = ModelCost(per_1k_input=price_in, per_1k_output=price_out)
    try:
        gov.check_budget(tenant, model, input_tokens, output_tokens)
    except BudgetExceededError as exc:
        console.print(f"[red]DENY[/] {exc}")
        raise typer.Exit(code=1)
    console.print(
        f"[green]ALLOW[/] tenant={tenant} model={model} "
        f"estimated=${gov.estimate(model, input_tokens, output_tokens):.4f}"
    )


if __name__ == "__main__":  # pragma: no cover
    cost_app()
