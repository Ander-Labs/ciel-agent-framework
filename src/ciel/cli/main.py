from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel import __version__
from ciel.runtime import ChatMessage, ChatRequest, DefaultAgentRuntime, DefaultToolDispatcher, ToolProvider, ToolRegistry

app = typer.Typer(name="ciel", help="Ciel Agent Framework CLI", no_args_is_help=True)
console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_runtime():
    """Construye un runtime para la CLI.

    Usa el proveedor remoto si ``CIEL_PROVIDER_URL`` está configurado, o un
    proveedor ``echo`` offline en caso contrario (para smoke tests sin red).
    """
    from ciel.providers import OpenAICompatibleProvider

    provider_url = os.getenv("CIEL_PROVIDER_URL")
    if provider_url:
        provider: object = OpenAICompatibleProvider(
            base_url=provider_url,
            api_key=os.getenv("CIEL_API_KEY"),
            default_model=os.getenv("CIEL_MODEL"),
        )
        console.print(f"[dim]chat: usando proveedor remoto {provider_url}[/]")
    else:
        provider = _EchoProvider()
        console.print("[dim]chat: sin CIEL_PROVIDER_URL; usando proveedor echo offline[/]")

    registry = ToolRegistry(default_toolset="default")
    dispatcher = DefaultToolDispatcher(
        provider=ToolProvider(registry=registry, require_tenant_on_execution=False),
        default_toolset="default",
    )
    return DefaultAgentRuntime(provider=provider, dispatcher=dispatcher)


class _EchoProvider:
    """Proveedor offline: devuelve ``echo:<prompt>`` sin red."""

    provider_name = "echo"

    async def complete(self, request: ChatRequest) -> object:
        from ciel.runtime import ChatChoice, ChatResponse

        prompt = request.messages[-1].content if request.messages else ""
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=f"echo:{prompt}"),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest) -> tuple:  # pragma: no cover - parity
        return (await self.complete(request),)

    async def models(self):  # pragma: no cover
        from ciel.providers import ModelInfo

        return [ModelInfo(id="echo", provider=self.provider_name)]


@app.callback()
def _callback(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log extended"),
) -> None:
    ctx.obj = {"verbose": verbose}


@app.command("doctor")
def doctor() -> None:
    table = Table(title="Environment")
    table.add_column("Item")
    table.add_column("Status")
    table.add_row("CLI version", _ok(f"{__version__}"))
    table.add_row("Python", _ok(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"))
    table.add_row("Repo root", _ok(str(REPO_ROOT)))
    console.print(table)


@app.command("run")
def run(
    agent: str = typer.Option(..., "--agent", "-a", help="Agent module or path"),
    input_file: Path | None = typer.Option(None, "--input", "-i", help="Input file"),
) -> None:
    console.print(f"[yellow]Running agent:[/] {agent}")
    if input_file:
        console.print(f"[yellow]Input:[/] {input_file}")
    console.print("[yellow]Not implemented yet.[/]")


@app.command("chat")
def chat(
    message: str = typer.Argument(..., help="Prompt a enviar al agente"),
    app_name: str = typer.Option("default", "--app", "-a", help="App name to chat with"),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Minimal output mode"),
    stream: bool = typer.Option(False, "--stream", help="Streaming en tiempo real (SSE por consola)"),
    tenant: Optional[str] = typer.Option(None, "--tenant", help="Tenant id (default $CIEL_TENANT)"),
) -> None:
    """Envía un prompt al runtime y muestra la respuesta.

    Con ``--stream`` se imprimen los fragmentos incrementalmente en tiempo real.
    Si el proveedor no implementa streaming, hace fallback a un único chunk con
    el texto completo.
    """
    effective_tenant = tenant or os.getenv("CIEL_TENANT")
    runtime = _build_runtime()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content=message),),
        tools=(),
    )

    if not quiet:
        console.print(f"[yellow]Chat with app:[/] {app_name}")

    if stream:
        _run_stream(runtime, request, effective_tenant)
        return

    result = asyncio.run(
        runtime.run_agent_loop(request=request, tenant_id=effective_tenant)
    )
    text = getattr(getattr(result.response, "choice", None), "message", None)
    text = getattr(text, "content", "") or ""
    if quiet:
        console.print(text)
    else:
        console.print(Panel.fit(text, title="Respuesta", border_style="blue"))


def _run_stream(runtime, request: ChatRequest, tenant: Optional[str]) -> None:
    """Imprime tokens en tiempo real usando ``runtime.stream_tokens``.

    ``stream_tokens`` re-emite el contenido *creciente* del assistant, así que
    aquí solo se imprime el delta respecto al fragmento anterior para evitar
    duplicados. Si no hay fragmentos, se imprime un aviso.
    """
    import anyio

    async def _consume() -> str:
        prior = ""
        last = ""
        async for token in runtime.stream_tokens(request=request, tenant_id=tenant):
            last = token
            delta = token[len(prior):]
            if delta:
                console.print(delta, end="")
            prior = token
        return last

    full = anyio.run(_consume)
    console.print()  # salto de línea final
    if not full:
        console.print("[yellow](sin contenido del proveedor)[/]")
@app.command("init")
def init(
    path: Path = typer.Argument(Path("."), help="Target directory (created if missing)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files"),
) -> None:
    """Scaffold a new Ciel project (pyproject + agent + ciel.yaml). Offline-safe."""
    from ciel.cli.scaffold import scaffold_project

    target = Path(path)
    created = scaffold_project(target, force=force)
    console.print(f"[green]Initialized Ciel project at[/] {target}")
    for rel in created:
        console.print(f"  [dim]+ {rel}[/]")


@app.command("compression")
def compression(
    target_dir: Path = typer.Option(..., "--target-dir", exists=True, file_okay=False, help="Project root for context loading"),
    max_chars: int = typer.Option(20000, "--max-chars", help="Context render budget in characters"),
) -> None:
    from ciel.runtime.context import load_project_context
    from ciel.runtime.context_compression import compress_context
    from ciel.runtime import ChatMessage

    context = load_project_context(path=str(target_dir))
    rendered = context.render(max_chars=max_chars) if context.files else ""
    placeholder_message = ChatMessage(role="system", content=rendered)
    summarized, slice_ = compress_context([placeholder_message], max_chars=max_chars)
    table = Table(title="Context compression summary")
    table.add_column("limit")
    table.add_column("removed")
    table.add_column("kept")
    table.add_row(str(max_chars), str(slice_.removed), str(slice_.keep_head))
    console.print(table)
    for message in summarized:
        console.print(message.content or "")


@app.command("checkpoints")
def checkpoints(
    session_root: Path = typer.Option(..., "--session-root", exists=True, file_okay=False, help="Directory containing session state"),
) -> None:
    table = Table(title="Checkpoints")
    table.add_column("checkpoint_id")
    table.add_column("path")
    table.add_column("status")
    table.add_row("cp-demo", str(session_root / "cp-demo.json"), "pending inspection")
    console.print(table)


@app.command("info")
def info() -> None:
    panel = Panel.fit(
        f"[bold]Ciel[/bold] {__version__}\nRepo: {REPO_ROOT}",
        title="Framework info",
        border_style="blue",
    )
    console.print(panel)


@app.command("version")
def version() -> None:
    console.print(f"Ciel {__version__}")


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8080, "--port", "-p", help="Bind port"),
    tenant: str | None = typer.Option(None, "--tenant", help="Default tenant id (else $CIEL_TENANT)"),
    otel: bool = typer.Option(False, "--otel", help="Enable OpenTelemetry tracing (in-memory or OTLP endpoint)"),
    otel_endpoint: str | None = typer.Option(None, "--otel-endpoint", help="OTLP collector endpoint (else in-memory exporter)"),
) -> None:
    """Run the composed Ciel gateway (control + MCP host + webhook) via uvicorn."""
    import uvicorn

    from ciel.gateway.server import make_app
    from ciel.observability.otel import OTEL_AVAILABLE, init_tracing

    effective_tenant = tenant or os.getenv("CIEL_TENANT")
    if otel:
        init_tracing(service_name="ciel", otlp_endpoint=otel_endpoint)
        otel_status = (
            f"OTLP {otel_endpoint}" if otel_endpoint else "in-memory exporter"
        ) if OTEL_AVAILABLE else "UNAVAILABLE (install ciel[observability])"
    else:
        otel_status = "disabled"
    app = make_app(tenant_id=effective_tenant)
    console.print(
        Panel.fit(
            f"[bold]Ciel[/bold] {__version__} — gateway\n"
            f"host={host} port={port} default_tenant={effective_tenant or '(none — tenant required per request)'}\n"
            f"tracing={otel_status}\n"
            f"[dim]surfaces: control / , MCP /mcp , webhook /v1/messaging/webhook , Teams/Discord/WebUI[/]",
            title="serve",
            border_style="blue",
        )
    )
    uvicorn.run(app, host=host, port=port)


@app.command("observe")
def observe(
    otel_endpoint: str | None = typer.Option(None, "--otel-endpoint", help="OTLP collector endpoint"),
) -> None:
    """Initialize a tracing session and report OpenTelemetry observability status.

    Useful as a smoke check of the observability stack: prints whether OTel is
    available, the active exporter, and the number of spans emitted so far.
    """
    from ciel.observability.otel import (
        OTEL_AVAILABLE,
        init_tracing,
        span_count,
    )

    if not OTEL_AVAILABLE:
        console.print(
            "[red]OpenTelemetry not available.[/] Install with: uv pip install 'ciel[observability]'"
        )
        raise typer.Exit(code=1)
    provider = init_tracing(service_name="ciel", otlp_endpoint=otel_endpoint)
    exporter_kind = "OTLP" if otel_endpoint else "in-memory"
    console.print(
        Panel.fit(
            f"[bold]Ciel observability[/bold]\n"
            f"OpenTelemetry: available\n"
            f"exporter: {exporter_kind}\n"
            f"spans emitted (this process): {span_count()}\n"
            f"[dim]Wire a collector (Tempo/Jaeger/OTel Collector) via --otel-endpoint in `ciel serve`.[/]",
            title="observe",
            border_style="blue",
        )
    )


def _ok(value: str) -> str:
    return f"[green]{value}[/]"


def _load_swarm_group():
    from ciel.cli.swarm import swarm_app as group
    return group


def _load_board_group():
    from ciel.cli.board import board_app as group
    return group


def _load_graph_group():
    from ciel.cli.graph import graph_app as group
    return group


def _load_flow_group():
    from ciel.cli.flow import flow_app as group
    return group


def _load_chat_group():
    from ciel.cli.chat import chat_app as group
    return group


def _load_root_group():
    from ciel.cli.root import root_app as group
    return group


def _load_loop_group():
    from ciel.cli.loop import loop_app as group
    return group


def _load_rbac_group():
    from ciel.cli.rbac import rbac_app as group
    return group


def _load_cost_group():
    from ciel.cli.cost import cost_app as group
    return group


app.add_typer(_load_swarm_group(), name="swarm")
app.add_typer(_load_board_group(), name="board")
app.add_typer(_load_graph_group(), name="graph")
app.add_typer(_load_flow_group(), name="flow")
app.add_typer(_load_chat_group(), name="chat")
app.add_typer(_load_root_group(), name="root")
app.add_typer(_load_loop_group(), name="loop")
app.add_typer(_load_rbac_group(), name="rbac")
app.add_typer(_load_cost_group(), name="cost")
