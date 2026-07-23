"""CLI `ciel reflect` — auto-reflexión e introspección del agente (Fase 19, v0.13).

Comandos:
  ciel reflect run --dataset <yaml> [--provider mock] [--threshold 0.8]
  ciel reflect history --name <prompt>
  ciel reflect introspect --session <id> [--tenant-id ...]

Offline-safe: ``--provider mock`` usa :class:`ciel.providers.MockProvider`
(determinista, sin red). Reutiliza :class:`ciel.eval.Evaluator` para medir los
KPIs de auto-aprendizaje sobre un dataset.

Funciones de lógica pura (``run_reflection``, ``prompt_history``,
``introspect_session``) se exponen para que los tests inyecten estado.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.table import Table

from ciel.eval import Evaluator, load_dataset

reflect_app = typer.Typer(
    name="reflect", help="Auto-reflexión e introspección del agente (offline-safe)"
)
console = Console()


# --------------------------------------------------------------------------- #
# Construcción del evaluable a partir de --provider / --model.
# --------------------------------------------------------------------------- #
async def _mock_callable(provider: Any, query: str, *, tenant_id: Optional[str] = None) -> str:
    from ciel.runtime import ChatRequest, ChatMessage

    resp = await provider.complete(
        ChatRequest(messages=[ChatMessage(role="user", content=query)])
    )
    return resp.choice.message.text()


def _build_agent(provider: str, *, model: Optional[str], mock_response: Optional[str]):
    """Construye el evaluable (callable async) a partir de los flags de la CLI."""
    from ciel.providers import MockProvider

    if provider == "mock" or (model and model.startswith("mock/")):
        mode = "fixed"
        if model and model.startswith("mock/"):
            sub = model[len("mock/"):]
            if sub in ("echo", "map", "fixed"):
                mode = sub
        if mock_response:
            mode = "fixed"
        prov = MockProvider(mode=mode, response=mock_response or "")
        if mode == "map":
            prov = MockProvider(mode="fixed", response=mock_response or "")

        async def agent_fixed(query, **kw):
            return await _mock_callable(prov, query)

        return agent_fixed
    raise typer.BadParameter(
        f"provider={provider!r} no soportado en CLI; usa --provider mock (o --model mock/...)"
    )


# --------------------------------------------------------------------------- #
# Lógica pura: run.
# --------------------------------------------------------------------------- #
def run_reflection(
    dataset_path: str,
    *,
    provider: str = "mock",
    model: Optional[str] = None,
    mock_response: Optional[str] = None,
    threshold: float = 0.8,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Corre un dataset y devuelve (resultados, kpis) midiendo auto-aprendizaje.

    Offline-safe: usa ``MockProvider`` por defecto (sin red).
    """
    cases = load_dataset(dataset_path)
    agent = _build_agent(provider, model=model, mock_response=mock_response)
    ev = Evaluator(agent=agent)
    results = ev.run(cases, threshold=threshold)
    return results, ev.kpis()


# --------------------------------------------------------------------------- #
# Lógica pura: historial de prompts versionados.
# --------------------------------------------------------------------------- #
def prompt_history(name: str, *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Devuelve el ``evolution_tree`` del prompt ``name`` (multitenant)."""
    from ciel.runtime.prompt_versioning import PromptRegistry
    from ciel.runtime.state_backend import build_state_backend

    backend = build_state_backend()
    reg = PromptRegistry(backend)
    return reg.evolution_tree(name, tenant_id=tenant_id)


# --------------------------------------------------------------------------- #
# Lógica pura: introspección de una sesión.
# --------------------------------------------------------------------------- #
def introspect_session(
    session_id: str, *, tenant_id: Optional[str] = None, limit: int = 16
) -> Dict[str, Any]:
    """Vuelca los últimos snapshots de ``cognitive_state_log`` de una sesión."""
    from ciel.runtime.cognitive_state import CognitiveState
    from ciel.runtime.memory_episodic import EpisodicStore
    from ciel.runtime.state_backend import build_state_backend

    backend = build_state_backend()
    store = EpisodicStore(backend)
    cog = CognitiveState(store=store, backend=backend)
    report = cog.get_recent(tenant_id=tenant_id, session_id=session_id, limit=limit)
    return report.to_dict()


# --------------------------------------------------------------------------- #
# Comandos Typer.
# --------------------------------------------------------------------------- #
@reflect_app.command("run")
def run_cmd(
    dataset: str = typer.Option(..., "--dataset", help="Ruta al YAML del dataset"),
    provider: str = typer.Option("mock", "--provider", help="Proveedor evaluable (mock)"),
    model: Optional[str] = typer.Option(None, "--model", help="Model id (p.ej. mock/echo)"),
    mock_response: Optional[str] = typer.Option(None, "--mock-response", help="Respuesta fija (modo fixed)"),
    threshold: float = typer.Option(0.8, "--threshold", help="Umbral mínimo de KPI para aprobar"),
):
    """Corre auto-reflexión sobre un dataset y reporta KPIs de aprendizaje."""
    _results, kpis = run_reflection(
        dataset,
        provider=provider,
        model=model,
        mock_response=mock_response,
        threshold=threshold,
    )
    table = Table(title="KPIs de auto-reflexión", show_lines=True)
    table.add_column("métrica")
    table.add_column("valor")
    table.add_row("casos", str(kpis["n"]))
    table.add_row("pasaron", str(kpis["passed"]))
    table.add_row("fallaron", str(kpis["failed"]))
    table.add_row("pass_rate", f"{kpis['pass_rate']:.3f}")
    for k, v in kpis["metrics"].items():
        table.add_row(k, f"{v:.3f}")
    console.print(table)
    if kpis["n"] and kpis["pass_rate"] < threshold:
        console.print(f"[red]✗ KPI pass_rate {kpis['pass_rate']:.3f} < umbral {threshold}[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ Auto-reflexión completa: {kpis['passed']}/{kpis['n']} pasaron[/]")


@reflect_app.command("history")
def history_cmd(
    name: str = typer.Option(..., "--name", help="Nombre del prompt versionado"),
    tenant_id: Optional[str] = typer.Option(None, "--tenant-id", help="Tenant del prompt"),
):
    """Imprime el evolution_tree del prompt versionado ``name``."""
    try:
        tree = prompt_history(name, tenant_id=tenant_id)
    except Exception as exc:  # prompt inexistente -> mensaje limpio
        console.print(f"[yellow]{exc}[/]")
        raise typer.Exit(code=1)
    table = Table(title=f"Evolución del prompt '{name}'", show_lines=True)
    table.add_column("versión")
    table.add_column("parent")
    table.add_column("sha256")
    table.add_column("changelog")
    for ver in tree.get("lineage", []):
        node = tree["nodes"].get(ver, {})
        table.add_row(
            ver,
            str(node.get("parent")),
            (node.get("sha256") or "")[:12],
            node.get("changelog") or "",
        )
    console.print(table)


@reflect_app.command("introspect")
def introspect_cmd(
    session: str = typer.Option(..., "--session", help="ID de sesión a inspeccionar"),
    tenant_id: Optional[str] = typer.Option(None, "--tenant-id", help="Tenant de la sesión"),
    limit: int = typer.Option(16, "--limit", help="Máximo de snapshots a volcar"),
):
    """Vuelca los últimos snapshots de estado cognitivo de una sesión."""
    data = introspect_session(session, tenant_id=tenant_id, limit=limit)
    snaps = data.get("snapshots", [])
    if not snaps:
        console.print(f"[yellow]Sin snapshots para session={session!r}[/]")
        return
    table = Table(title=f"Estado cognitivo — session {session}", show_lines=True)
    table.add_column("versión prompt")
    table.add_column("turnos mem")
    table.add_column("tools")
    table.add_column("fallo")
    table.add_column("confianza")
    table.add_column("rationale")
    for s in snaps:
        table.add_row(
            str(s.get("active_prompt_version")),
            str(s.get("memory_turn_count")),
            str(len(s.get("tool_calls") or [])),
            "sí" if s.get("had_failure") else "no",
            f"{float(s.get('confidence', 1.0)):.2f}",
            s.get("rationale") or "",
        )
    console.print(table)


__all__ = [
    "reflect_app",
    "run_reflection",
    "prompt_history",
    "introspect_session",
]
