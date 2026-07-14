from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration import AgentSpec
from ciel.orchestration.budget import Budget, RateLimiter
from ciel.orchestration.supervisor import Supervisor, Worker
from ciel.orchestration.topology import TopologyEngine

console = Console()
swarm_app = typer.Typer(name="swarm", help="Run agent swarms from an AgentSpec")


class _NoCounter:
    def exceed(self, budget):
        return None

    def consume_tool(self, count: int = 1) -> None:
        return None


@dataclass
class _AdHocContext:
    step_id: str
    worker_id: str
    payload: Optional[Dict[str, Any]] = None


class _SupervisorStepRunner:
    def __init__(self, supervisor: Supervisor) -> None:
        self.supervisor = supervisor

    async def run(self, step: Any) -> Any:
        result = await self.supervisor.run(
            step.id,
            self._worker_for(step.id),
            payload=None,
            worker_id=f"step-{step.id}",
        )
        return result.output

    def _worker_for(self, step_id: str) -> Worker:
        async def _execute(ctx: WorkerContext) -> Dict[str, Any]:
            return {"output": {"step_id": ctx.step_id, "worker_id": ctx.worker_id}}
        return _execute


@swarm_app.command("run")
def swarm_run(
    spec: typer.FileText = typer.Option(..., "--spec", "-s", help="YAML AgentSpec file"),
    max_tools: int = typer.Option(8, "--max-tools", help="Max tool calls"),
    max_tokens: int | None = typer.Option(None, "--max-tokens", help="Max token count"),
    seconds: float = typer.Option(60.0, "--seconds", help="Max wall-clock seconds"),
    rate_limit: int = typer.Option(0, "--rate-limit", help="Per-step rate limit (0 disables)"),
) -> None:
    agent_spec = AgentSpec.from_yaml(spec.read())
    budget = Budget(max_tools=max_tools, max_tokens=max_tokens, max_seconds=seconds)
    rate_limiter = RateLimiter() if rate_limit > 0 else None
    rate_limits = {step.id: rate_limit for step in agent_spec.steps} if rate_limiter is not None else {}

    supervisor = Supervisor(
        budget=budget,
        agent_counter=_NoCounter(),
        rate_limit=rate_limit,
        rate_limiter=rate_limiter,
    )
    runner = _SupervisorStepRunner(supervisor=supervisor)

    async def run_swarm() -> None:
        engine = TopologyEngine(
            agent_spec,
            runner=runner,
            budget=budget,
            rate_limiter=rate_limiter,
            rate_limits=rate_limits,
        )
        outputs = await engine.run()
        rows = outputs if isinstance(outputs, list) else [outputs]
        table = Table(title=f"Swarm: {agent_spec.name}")
        table.add_column("step")
        table.add_column("output")
        for row in rows:
            step_id = row.get("step_id") if isinstance(row, dict) else str(row)
            table.add_row(str(step_id), str(row))
        console.print(table)
        console.print(Panel.fit(f"max_tools={budget.max_tools}\nmax_tokens={budget.max_tokens}\nmax_seconds={budget.max_seconds}", title="Budget", border_style="blue"))

    try:
        asyncio.run(run_swarm())
    except KeyboardInterrupt:
        raise typer.Exit(0)
