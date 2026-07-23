"""Test de introspección / estado cognitivo (Fase 19, v0.13.0).

Verifica que tras un run se registra un CognitiveSnapshot en cognitive_state_log
(backend multitenant), que Agent.introspect() lo recupera, y el aislamiento por
tenant. OFFLINE: providers dummy sin red.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.cognitive_state import (
    CognitiveSnapshot,
    CognitiveState,
    IntrospectionConfig,
    IntrospectionReport,
    install_cognitive_state_support,
)
from ciel.runtime.memory_episodic import EpisodicStore, MemoryConfig
from ciel.runtime.state_backend import SqliteStateBackend

from ciel.api import Agent


class TextProvider(ChatProvider):
    provider_name = "dummy-cog"

    def __init__(self, text: str = "Hola."):
        self._text = text

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=self._text),
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
    tmp = tempfile.mkdtemp(prefix="ciel-cog-test-")
    db = str(Path(tmp) / "state.sqlite")
    be = SqliteStateBackend(db)
    yield be
    be.close()


def test_snapshot_recorded_post_run(backend):
    install_cognitive_state_support(Agent)
    store = EpisodicStore(backend)
    agent = Agent(
        provider=TextProvider("respuesta"),
        tools=[],
        introspection=True,
        memory=store,
        memory_config=MemoryConfig(),
    )
    resp = agent.run("hola", tenant_id="t1")
    assert resp.text == "respuesta"
    # introspect recupera snapshots
    report = agent.introspect()
    assert isinstance(report, IntrospectionReport)
    assert len(report.snapshots) >= 1
    snap = report.latest
    assert isinstance(snap, CognitiveSnapshot)
    assert snap.tenant_id == "t1"
    assert snap.had_failure is False
    assert 0.0 <= snap.confidence <= 1.0


def test_state_log_backend_entries(backend):
    # Sin memoria configurada, el agente usa un StateBackend por-proceso.
    # Verificamos el contrato público: el snapshot queda registrado y es
    # recuperable vía agent.introspect().
    install_cognitive_state_support(Agent)
    agent = Agent(provider=TextProvider(), tools=[], introspection=True)
    agent.run("hola", tenant_id="t1")
    report = agent.introspect()
    assert len(report.snapshots) >= 1
    assert report.snapshots[0].tenant_id == "t1"


def test_tenant_isolation(backend):
    install_cognitive_state_support(Agent)
    store = EpisodicStore(backend)
    agent_a = Agent(provider=TextProvider(), tools=[], introspection=True, memory=store, memory_config=MemoryConfig())
    agent_b = Agent(provider=TextProvider(), tools=[], introspection=True, memory=store, memory_config=MemoryConfig())
    agent_a.run("a", tenant_id="tenantA")
    agent_b.run("b", tenant_id="tenantB")
    sa = agent_a.introspect()
    sb = agent_b.introspect()
    assert all(s.tenant_id == "tenantA" for s in sa.snapshots)
    assert all(s.tenant_id == "tenantB" for s in sb.snapshots)


def test_disabled_no_entries(backend):
    install_cognitive_state_support(Agent)
    agent = Agent(provider=TextProvider(), tools=[], introspection_config=IntrospectionConfig(enabled=False))
    agent.run("hola", tenant_id="t1")
    report = agent.introspect()
    assert report.snapshots == []


def test_introspection_block_injected(backend):
    install_cognitive_state_support(Agent)
    store = EpisodicStore(backend)
    # Primer run: registra snapshot.
    agent = Agent(provider=TextProvider(), tools=[], introspection=True, memory=store, memory_config=MemoryConfig())
    agent.run("primero", tenant_id="t1")
    # Segundo run: el bloque [Estado cognitivo] debe inyectarse en el system.
    req = agent._build_request("segundo", tenant_id="t1", session_id=_session_of(agent))
    sys_texts = [m.content for m in req.messages if m.role == "system"]
    assert any("[Estado cognitivo]" in t for t in sys_texts)


def _session_of(agent: Agent) -> str:
    return agent._cognitive.session_id  # type: ignore[attr-defined]
