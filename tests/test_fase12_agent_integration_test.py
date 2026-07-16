"""Fase 12 Item 5 — Integración con ciel.Agent (offline).

Cubre:
  * ``@ciel.skill`` registra la función en la SkillLibrary global (singleton).
  * ``Agent(skills=['nombre'])`` carga el skill como ToolFunction ejecutable
    (vía el registry existente) y puede invocarse a través del runtime.
  * ``agent.teach(skill)`` registra un skill verificado en runtime.

OFFLINE-SAFE: providers dummy locales, sin red ni API keys.
"""

from __future__ import annotations

import ciel
import pytest
from ciel.providers import ChatProvider
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse
from ciel.runtime.skills import Skill
from ciel.runtime.skill_agent_integration import (
    global_skill_library,
    skill,
    teach,
)

from ciel.api import Agent, ToolFunction


# --------------------------------------------------------------------------- #
# Providers dummy OFFLINE
# --------------------------------------------------------------------------- #
class _EchoToolProvider(ChatProvider):
    """Responde un tool_call con el nombre que le pidan, luego texto final."""

    provider_name = "dummy-skill"

    def __init__(self, *, tool_name: str, args: dict):
        self._tool_name = tool_name
        self._args = args

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # Primer turno: pedir la herramienta; segundo turno: texto final.
        tools_present = bool(request.tools)
        # Detectamos si ya hubo un resultado de tool para cortar el loop.
        already_called = any(
            getattr(m, "role", None) == "tool" for m in request.messages
        )
        if tools_present and not already_called:
            tc = [
                {
                    "id": "call_1",
                    "name": self._tool_name,
                    "arguments": self._args,
                }
            ]
            return ChatResponse(
                choice=ChatChoice(
                    message=ChatMessage(role="assistant", content="", tool_calls=tc),
                    finish_reason="tool_calls",
                ),
                metadata={"tool_calls": tc},
            )
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content="Listo."),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):  # pragma: no cover
        return (await self.complete(request),)

    async def models(self):  # pragma: no cover
        return ()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_skill_decorator_registers_in_global_library():
    @skill
    def multiply(a: int, b: int) -> int:
        "Multiplica dos enteros."
        return a * b

    stored = global_skill_library.get("multiply")
    assert stored is not None
    assert stored.name == "multiply"
    assert "Multiplica" in stored.description
    # La función original queda guardada para exposición como tool.
    assert callable(stored.metadata.get("_callable"))
    # El decorador devuelve la función original (sigue siendo invocable).
    assert multiply(3, 4) == 12


def test_skill_decorator_with_explicit_name_and_category():
    @skill(name="greeter", category="text")
    def _greet(name: str) -> str:
        "Saluda."
        return f"hi {name}"

    stored = global_skill_library.get("greeter")
    assert stored is not None
    assert stored.category == "text"
    assert stored.name == "greeter"


def test_skill_decorator_rejects_bad_syntax(monkeypatch):
    # Forzamos un source inválido simulando que inspect.getsource devuelve basura.
    import ciel.runtime.skill_agent_integration as sai

    def _bad_source(fn):
        return "def broken(:  # sintaxis inválida\n    return 1\n"

    monkeypatch.setattr(sai, "_function_source", _bad_source)
    from ciel.runtime.skills_lib import SkillError

    with pytest.raises(SkillError):

        @sai.skill
        def wont_matter(x):
            return x


def test_agent_skills_loads_skill_as_executable_tool():
    @skill
    def add(a: int, b: int) -> int:
        "Suma dos enteros."
        return a + b

    provider = _EchoToolProvider(tool_name="add", args={"a": 2, "b": 5})
    agent = Agent(provider=provider, skills=["add"])

    # El skill quedó cargado en el registry del agente como spec ejecutable.
    assert "add" in agent.registry.tool_names(agent.toolset)
    spec_names = [s.name for s in agent._tool_specs]
    assert "add" in spec_names

    # Ejecutamos el runtime: el provider pide 'add' y debe correr el skill.
    resp = agent.run("suma 2 y 5")
    results = resp.tool_results
    assert len(results) == 1
    assert results[0].name == "add"
    assert results[0].error is None
    # La salida del skill ejecutado.
    assert results[0].output == 7


def test_agent_skills_unknown_name_raises():
    from ciel.runtime.skills_lib import SkillError

    with pytest.raises(SkillError):
        Agent(provider=_EchoToolProvider(tool_name="x", args={}), skills=["does_not_exist"])


def test_agent_teach_registers_verified_skill():
    @skill
    def subtract(a: int, b: int) -> int:
        "Resta dos enteros."
        return a - b

    provider = _EchoToolProvider(tool_name="subtract", args={"a": 10, "b": 3})
    agent = Agent(provider=provider)  # sin skills en __init__
    assert "subtract" not in agent.registry.tool_names(agent.toolset)

    # teach con verificación offline (casos de prueba).
    tf = agent.teach(
        global_skill_library.get("subtract"),
        test_cases=[{"call": {"a": 10, "b": 3}, "expect": 7}],
    )
    assert isinstance(tf, ToolFunction)
    assert "subtract" in agent.registry.tool_names(agent.toolset)

    resp = agent.run("resta 10 menos 3")
    results = resp.tool_results
    assert len(results) == 1
    assert results[0].output == 7


def test_agent_teach_rejects_failing_verification():
    @skill
    def buggy(a: int) -> int:
        "Siempre devuelve 0."
        return 0

    agent = Agent(provider=_EchoToolProvider(tool_name="buggy", args={"a": 5}))
    from ciel.runtime.skills_lib import SkillVerificationError

    with pytest.raises(SkillVerificationError):
        agent.teach(
            global_skill_library.get("buggy"),
            test_cases=[{"call": {"a": 5}, "expect": 999}],  # espera distinto -> falla
        )
    # No se registró porque la verificación falló.
    assert "buggy" not in agent.registry.tool_names(agent.toolset)


def test_teach_helper_function_standalone():
    @skill
    def echo(msg: str) -> str:
        "Devuelve el mensaje."
        return msg

    provider = _EchoToolProvider(tool_name="echo", args={"msg": "hola"})
    agent = Agent(provider=provider)
    tf = teach(agent, global_skill_library.get("echo"))
    assert isinstance(tf, ToolFunction)
    assert "echo" in agent.registry.tool_names(agent.toolset)


def test_existing_agent_api_unchanged():
    # Sin skills: comportamiento histórico intacto.
    agent = Agent(provider=_EchoToolProvider(tool_name="x", args={}))
    assert agent.toolset == "default"
    assert agent.registry.tool_names(agent.toolset) == ()


def test_ciel_namespace_exposes_skill_decorator():
    assert hasattr(ciel, "skill")
    assert hasattr(ciel, "teach")
