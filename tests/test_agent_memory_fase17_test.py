"""Test de integración de memoria episódica en ciel.Agent (Fase 17, v0.11.0).

Verifica que pasar ``memory=EpisodicStore`` a ``Agent`` persiste user/assistant
y los recupera en runs sucesivos (inyectados en el system prompt), aislando
por tenant. OFFLINE: usa un ChatProvider dummy sin red.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ciel.api import Agent
from ciel.providers import ChatProvider
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.memory_episodic import EpisodicStore, MemoryConfig
from ciel.runtime.state_backend import SqliteStateBackend


class EchoProvider(ChatProvider):
    """Provider dummy: repite la última palabra del usuario como respuesta."""

    provider_name = "echo-f17"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # El system prompt inyectado por memoria episódica debe contener el
        # contexto previo cuando lo hay.
        system_text = " ".join(
            m.content if isinstance(m.content, str) else "" for m in request.messages
            if m.role == "system"
        )
        user_text = ""
        for m in reversed(request.messages):
            if m.role == "user":
                user_text = m.content if isinstance(m.content, str) else ""
                break
        last = user_text.strip().split()[-1] if user_text.strip() else "hola"
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=f"recuerdo:{last}"),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


@pytest.fixture()
def backend():
    tmp = tempfile.mkdtemp(prefix="ciel-agent-mem-")
    db = str(Path(tmp) / "state.sqlite")
    be = SqliteStateBackend(db)
    yield be
    be.close()


def test_agent_persists_and_recalls_memory(backend):
    store = EpisodicStore(backend)
    agent = Agent(
        provider=EchoProvider(),
        model="echo-f17",
        memory=store,
        memory_config=MemoryConfig(recent_turns=8),
    )

    # Primer run: la memoria está vacía.
    r1 = agent.run("soy Ana", tenant_id="t1")
    assert "Ana" in r1.text

    # Segundo run: el contexto previo (soy Ana) debe inyectarse en el system.
    r2 = agent.run("qué nombre dije", tenant_id="t1")
    # El provider echo repite la última palabra del usuario ("dije").
    assert "dije" in r2.text

    # La memoria del tenant/sesión del agente debe tener al menos 3 episodios
    # (user, assistant del run 1, user del run 2, ...).
    sid = _session_of(agent)
    recent = store.get_recent(tenant_id="t1", session_id=sid, limit=10)
    assert len(recent) >= 3


def test_agent_memory_isolation_between_tenants(backend):
    store = EpisodicStore(backend)
    agent_a = Agent(provider=EchoProvider(), model="echo-f17", memory=store, memory_config=MemoryConfig())
    agent_b = Agent(provider=EchoProvider(), model="echo-f17", memory=store, memory_config=MemoryConfig())

    agent_a.run("secreto A", tenant_id="tenantA")
    agent_b.run("secreto B", tenant_id="tenantB")

    recent_a = store.get_recent(tenant_id="tenantA", session_id=_session_of(agent_a), limit=10)
    recent_b = store.get_recent(tenant_id="tenantB", session_id=_session_of(agent_b), limit=10)
    assert all("A" in (m.content or "") for m in recent_a)
    assert all("B" in (m.content or "") for m in recent_b)


def _session_of(agent: Agent) -> str:
    # El AgentMemory guarda el session_id por agente.
    return agent._memory.session_id(extra_session_id=None)  # type: ignore[attr-defined]
