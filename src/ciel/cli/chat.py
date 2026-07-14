from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ciel.orchestration import (
    Agent,
    GroupChat,
    GroupChatManager,
    GroupChatState,
)
from ciel.orchestration.supervisor import Supervisor

console = Console()
chat_app = typer.Typer(name="chat", help="Run group chats (AutoGen-style, offline-safe)")


def _reviewer(state: GroupChatState) -> str:
    """Revisor: propone en su primera ronda; cuando coder y tester ya
    reaccionaron a la propuesta, aprueba y emite TERMINATE (converge)."""
    roles = [m.role for m in state.transcript]
    has_proposal = any("Propuesta:" in m.content for m in state.transcript)
    has_reviewer = "reviewer" in roles
    if not has_reviewer:
        return "Propuesta: disenar feature de login con JWT y refresh tokens."
    if has_proposal and "coder" in roles and "tester" in roles:
        return "Aprobado: propuesta + implementacion + pruebas correctas. TERMINATE"
    return "ok, continuemos revisando."


def _coder(state: GroupChatState) -> str:
    """Codificador: reacciona a la propuesta/ultimo mensaje."""
    last = state.transcript[-1].content if state.transcript else ""
    return f"Implemento: {last}"


def _tester(state: GroupChatState) -> str:
    """Tester: valida la implementacion/ultimo mensaje."""
    last = state.transcript[-1].content if state.transcript else ""
    return f"Testeo: {last}"


def _build_demo_chat(max_rounds: int) -> GroupChat:
    """Group chat de DEMOSTRACION EN MEMORIA con 3 agentes locales.

    No usa red ni proveedor; cada ``responder`` opera sobre ``state.transcript``
    (OFFLINE-SAFE). El revisor emite ``TERMINATE`` cuando ya existe propuesta,
    implementacion y pruebas -> el chat converge deterministicamente.
    """
    participants = [
        Agent(name="reviewer", responder=_reviewer, system_message="Revisor del diseno"),
        Agent(name="coder", responder=_coder, system_message="Implementador"),
        Agent(name="tester", responder=_tester, system_message="Validador"),
    ]
    return GroupChat(
        participants,
        max_rounds=max_rounds,
        terminate_keyword="TERMINATE",
    )


def _print_transcript(state: GroupChatState, title: str = "Group chat") -> None:
    """Imprime con Rich el transcripto (role/content/round) y un Panel resumen."""
    table = Table(title=title)
    table.add_column("round")
    table.add_column("role")
    table.add_column("content", overflow="fold")
    for msg in state.transcript:
        table.add_row(str(msg.round), msg.role, msg.content)
    console.print(table)
    console.print(
        Panel.fit(
            f"rounds: {state.rounds}\n"
            f"terminated: {state.terminated}\n"
            f"terminator: {state.terminator or '(none)'}",
            title="Summary",
            border_style="blue",
        )
    )


@chat_app.command("group")
def group(
    message: str = typer.Option(
        "Tarea: disenar feature de login",
        "--message",
        "-m",
        help="Mensaje inicial del usuario que dispara el chat",
    ),
    rounds: int = typer.Option(
        12, "--rounds", "-r", help="Numero maximo de rondas antes de forzar fin"
    ),
    tenant: Optional[str] = typer.Option(
        None, "--tenant", help="Tenant id (para trazabilidad)"
    ),
) -> None:
    """Run an offline 3-agent group chat that converges with TERMINATE."""
    chat = _build_demo_chat(max_rounds=rounds)
    manager = GroupChatManager(chat, supervisor=Supervisor(), tenant_id=tenant)

    async def _run() -> GroupChatState:
        return await manager.run(initial_message=message, initial_sender="user")

    try:
        state = asyncio.run(_run())
    except KeyboardInterrupt:
        raise typer.Exit(0)

    _print_transcript(state, title="Group chat (offline demo)")
    console.print(
        Panel.fit(
            "Offline demo: reviewer -> coder -> tester (round-robin).\n"
            "El revisor emite TERMINATE cuando hay propuesta + implementacion + pruebas.\n"
            "No provider, no network required.",
            title="Summary",
            border_style="blue",
        )
    )
    if not state.terminated:
        console.print("[yellow]chat finished without explicit TERMINATE (max rounds).[/]")


__all__ = ["chat_app", "group"]


if __name__ == "__main__":
    chat_app()
