"""Test de self-reflection + learning-from-failure (Fase 19, v0.13.0).

Verifica detección de fallo de tool, persistencia de lección (memoria
episódica role='lesson') y degradación graceful cuando está deshabilitado.
OFFLINE: providers dummy sin red.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.memory_episodic import EpisodicStore, MemoryConfig
from ciel.runtime.reflection_agent_integration import (
    AgentReflection,
    ReflectionConfig,
    install_agent_reflection_support,
)
from ciel.runtime.state_backend import SqliteStateBackend

from ciel.api import Agent


class FailingToolCallProvider(ChatProvider):
    """Turno 1: pide la tool que falla. Turno 2: responde texto."""

    provider_name = "dummy-reflect-fail"

    def __init__(self, fail_name: str):
        self._fail_name = fail_name
        self._turns = [
            [{"id": "c1", "name": fail_name, "arguments": {"x": 1}}],
        ]

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self._turns:
            tc = self._turns.pop(0)
            return ChatResponse(
                choice=ChatChoice(
                    message=ChatMessage(role="assistant", content="", tool_calls=tc),
                    finish_reason="tool_calls",
                ),
                metadata={"tool_calls": tc},
            )
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content="Hecho."),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


class OkToolCallProvider(ChatProvider):
    """Turno 1: pide la tool que funciona. Turno 2: responde texto."""

    provider_name = "dummy-reflect-ok"

    def __init__(self, ok_name: str):
        self._ok_name = ok_name
        self._turns = [
            [{"id": "c1", "name": ok_name, "arguments": {"x": 1}}],
        ]

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self._turns:
            tc = self._turns.pop(0)
            return ChatResponse(
                choice=ChatChoice(
                    message=ChatMessage(role="assistant", content="", tool_calls=tc),
                    finish_reason="tool_calls",
                ),
                metadata={"tool_calls": tc},
            )
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content="Éxito."),
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
    tmp = tempfile.mkdtemp(prefix="ciel-reflect-test-")
    db = str(Path(tmp) / "state.sqlite")
    be = SqliteStateBackend(db)
    yield be
    be.close()


def _session_of(agent: Agent) -> str:
    return agent._memory.session_id(extra_session_id=None)  # type: ignore[attr-defined]


def test_detect_failure_and_persist_lesson(backend):
    install_agent_reflection_support(Agent)
    store = EpisodicStore(backend)
    agent = Agent(
        provider=FailingToolCallProvider("boom"),
        tools=[_failing_tool()],
        reflection=store,
        memory=store,
        memory_config=MemoryConfig(),
    )
    resp = agent.run("usa boom", tenant_id="t1")
    # fallo detectado
    assert resp.tool_results[0].error is not None
    # reflection resumen en AgentResponse
    refl = resp.reflection
    assert refl is not None
    assert refl["had_failure"] is True
    assert "boom" in refl["failed_tools"]
    # lección persistida como memoria episódica role='lesson'
    sid = _session_of(agent)
    lessons = agent._reflection.lessons(tenant_id="t1", session_id=sid)
    assert len(lessons) >= 1
    assert lessons[0]["type"] == "learning_from_failure"
    assert "boom" in lessons[0]["summary"]


def test_no_failure_no_lesson(backend):
    install_agent_reflection_support(Agent)
    store = EpisodicStore(backend)
    agent = Agent(
        provider=OkToolCallProvider("ok"),
        tools=[_ok_tool()],
        reflection=store,
        memory=store,
        memory_config=MemoryConfig(),
    )
    resp = agent.run("usa ok", tenant_id="t1")
    refl = resp.reflection
    assert refl["had_failure"] is False
    sid = _session_of(agent)
    lessons = agent._reflection.lessons(tenant_id="t1", session_id=sid)
    assert lessons == []


def test_disabled_noop():
    # El install corre globalmente en api.py; sin reflection= queda deshabilitado.
    agent = Agent(provider=OkToolCallProvider("ok"), tools=[_ok_tool()])
    assert agent._reflection.enabled is False
    resp = agent.run("usa ok", tenant_id="t1")
    # AgentResponse.reflection debe ser None (aditivo, sin romper)
    assert resp.reflection is None


def test_reflection_config_disabled():
    install_agent_reflection_support(Agent)
    agent = Agent(
        provider=OkToolCallProvider("ok"),
        tools=[_ok_tool()],
        reflection_config=ReflectionConfig(enabled=False),
    )
    assert agent._reflection.enabled is False
    resp = agent.run("usa ok", tenant_id="t1")
    assert resp.reflection is None


def test_isolation_of_lessons(backend):
    install_agent_reflection_support(Agent)
    store = EpisodicStore(backend)
    agent_a = Agent(provider=FailingToolCallProvider("boom"), tools=[_failing_tool()],
                    reflection=store, memory=store, memory_config=MemoryConfig())
    agent_b = Agent(provider=OkToolCallProvider("ok"), tools=[_ok_tool()],
                    reflection=store, memory=store, memory_config=MemoryConfig())
    agent_a.run("falla", tenant_id="tenantA")
    agent_b.run("ok", tenant_id="tenantB")
    lessons_a = agent_a._reflection.lessons(tenant_id="tenantA", session_id=_session_of(agent_a))
    lessons_b = agent_b._reflection.lessons(tenant_id="tenantB", session_id=_session_of(agent_b))
    assert len(lessons_a) >= 1
    assert lessons_b == []


# --- tools locales ----------------------------------------------------------


def _failing_tool():
    from ciel.api import tool

    @tool
    def boom(x: int) -> int:
        """Tool que siempre falla."""
        raise RuntimeError("boom falló")

    return boom


def _ok_tool():
    from ciel.api import tool

    @tool
    def ok(x: int) -> int:
        """Tool que funciona."""
        return x * 2

    return ok
