"""Tests para el GROUP CHAT estilo AutoGen (Fase 5).

Cubre: convergencia de un group chat de 3 agentes (reviewer/coder/tester),
orden y roles del transcripto, agotamiento de ``max_rounds`` sin terminar,
selector explícito, terminación vía ``terminate_if`` (sin palabra clave) y
persistencia del transcripto con ``GroupChatCheckpointStore`` + ``MemoryStore``.

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from ciel.orchestration import (
    Agent,
    ChatMessage,
    GroupChat,
    GroupChatCheckpointStore,
    GroupChatError,
    GroupChatManager,
    GroupChatState,
)
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


def _roles(transcript):
    return [m.role for m in transcript]


def _build_converge_chat(*, max_rounds=12, selector=None, terminate_keyword="TERMINATE"):
    """Group chat de 3 agentes que CONVERGE: el reviewer emite TERMINATE
    en cuanto detecta una propuesta + implementación + test en el transcripto.

    Orden round-robin: reviewer, coder, tester, reviewer, ...
    """

    def reviewer(state: GroupChatState) -> str:
        roles = _roles(state.transcript)
        if "coder" in roles and "tester" in roles and "reviewer" in roles:
            return "All artifacts present (proposal, implementation, tests). TERMINATE"
        return "Please propose a plan, then implement and test it."

    def coder(state: GroupChatState) -> str:
        return "I have implemented the solution."

    def tester(state: GroupChatState) -> str:
        return "Tests pass."

    participants = [
        Agent(name="reviewer", responder=reviewer),
        Agent(name="coder", responder=coder),
        Agent(name="tester", responder=tester),
    ]
    chat = GroupChat(
        participants,
        max_rounds=max_rounds,
        selector=selector,
        terminate_keyword=terminate_keyword,
    )
    return chat


# --------------------------------------------------------------------------- #
# 1. Group chat de 3 agentes CONVERGE (uno emite TERMINATE)
# --------------------------------------------------------------------------- #
def test_three_agent_chat_converges_with_terminate():
    chat = _build_converge_chat()
    manager = GroupChatManager(chat, supervisor=None)  # Supervisor() por defecto

    state = asyncio.run(manager.run())

    # Convergió dentro de max_rounds y el terminador es quien emitió TERMINATE.
    assert state.terminated is True
    assert state.terminator == "reviewer"
    assert state.rounds <= chat.max_rounds
    # El último mensaje contiene la palabra clave y fue del reviewer.
    last = state.last_message()
    assert last is not None
    assert last.role == "reviewer"
    assert chat.terminate_keyword in last.content


# --------------------------------------------------------------------------- #
# 2. Transcripción en orden con roles correctos; mensaje inicial
# --------------------------------------------------------------------------- #
def test_transcript_order_and_initial_sender():
    chat = _build_converge_chat()
    manager = GroupChatManager(chat)

    state = asyncio.run(
        manager.run(initial_message="Please solve the task.", initial_sender="user")
    )

    assert state.rounds >= 1
    # Primer mensaje es el inicial del sender indicado, en ronda 0.
    first = state.transcript[0]
    assert isinstance(first, ChatMessage)
    assert first.role == "user"
    assert first.content == "Please solve the task."
    assert first.round == 0

    # Los mensajes posteriores respetan el orden round-robin de hablantes.
    roles = _roles(state.transcript)
    assert roles[0] == "user"
    assert roles[1] == "reviewer"
    assert roles[2] == "coder"
    assert roles[3] == "tester"
    # Las rondas son crecientes a partir de 1.
    rounds_seq = [m.round for m in state.transcript[1:]]
    assert rounds_seq == sorted(rounds_seq)
    assert rounds_seq[0] == 1


# --------------------------------------------------------------------------- #
# 3. max_rounds se agota sin terminar -> terminated por límite, terminator None
# --------------------------------------------------------------------------- #
def test_max_rounds_exhausted_without_terminate():
    # Agentes que NUNCA emiten señal de terminación.
    def chatter(state: GroupChatState) -> str:
        return "still working..."

    participants = [
        Agent(name="a", responder=chatter),
        Agent(name="b", responder=chatter),
        Agent(name="c", responder=chatter),
    ]
    chat = GroupChat(participants, max_rounds=3, terminate_keyword="TERMINATE")
    manager = GroupChatManager(chat)
    assert chat.participant_names() == ["a", "b", "c"]

    state = asyncio.run(manager.run())

    # No hubo TERMINATE ni terminator explícito; se agotó el límite.
    assert not any(chat.terminate_keyword in m.content for m in state.transcript)
    assert state.terminated is True
    assert state.terminator is None
    assert state.rounds == chat.max_rounds


# --------------------------------------------------------------------------- #
# 4. selector explícito que siempre devuelve un agente concreto
# --------------------------------------------------------------------------- #
def test_explicit_selector_forces_speaker_order():
    def pick_tester(state: GroupChatState, participants) -> str:
        return "tester"

    chat = _build_converge_chat(selector=pick_tester, max_rounds=3)
    manager = GroupChatManager(chat)

    state = asyncio.run(
        manager.run(initial_message="go", initial_sender="user")
    )

    # Todos los hablantes tras el mensaje inicial son "tester" (selector fijo).
    post_initial = state.transcript[1:]
    assert len(post_initial) == chat.max_rounds
    assert all(m.role == "tester" for m in post_initial)


# --------------------------------------------------------------------------- #
# 5. terminate_if (sin palabra clave) finaliza la conversación
# --------------------------------------------------------------------------- #
def test_terminate_if_without_keyword():
    def alice(state: GroupChatState) -> str:
        return "here is the proposal"

    def bob(state: GroupChatState) -> str:
        # Bob reacciona a la propuesta de Alice.
        last = state.last_message()
        if last is not None and "proposal" in last.content:
            return "approved"
        return "waiting for proposal"

    def bob_terminates(text: str) -> bool:
        return text == "approved"

    participants = [
        Agent(name="alice", responder=alice),
        Agent(name="bob", responder=bob, terminate_if=bob_terminates),
    ]
    # Sin palabra clave: nada corta por keyword.
    chat = GroupChat(participants, max_rounds=10, terminate_keyword="")
    manager = GroupChatManager(chat)

    state = asyncio.run(manager.run())

    assert state.terminated is True
    assert state.terminator == "bob"
    # El último mensaje de bob es "approved" (disparó terminate_if).
    assert state.last_message().role == "bob"
    assert state.last_message().content == "approved"


# --------------------------------------------------------------------------- #
# 6. Checkpointer: tras run() el transcripto persiste y se puede cargar
# --------------------------------------------------------------------------- #
def test_checkpoint_store_persists_transcript():
    store, path = _make_store()
    try:
        chat = _build_converge_chat()
        manager = GroupChatManager(chat, tenant_id="t1", session_id="s1")
        cp_store = GroupChatCheckpointStore(store)

        state = asyncio.run(manager.run())
        assert state.terminated is True

        run_id = "chat-run-1"
        cp_store.save(run_id=run_id, state=state, tenant_id="t1", session_id="s1")

        loaded = cp_store.load(run_id=run_id, tenant_id="t1", session_id="s1")
        assert loaded is not None
        assert loaded["run_id"] == run_id
        assert "state" in loaded

        restored = GroupChatState.from_snapshot(loaded["state"])
        # El transcripto persistido coincide con el estado original.
        assert len(restored.transcript) == len(state.transcript)
        assert restored.terminated == state.terminated
        assert restored.terminator == state.terminator
        assert restored.transcript[-1].content == state.transcript[-1].content
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 7. GroupChat sin participantes lanza GroupChatError
# --------------------------------------------------------------------------- #
def test_group_chat_without_participants_raises():
    with pytest.raises(GroupChatError):
        GroupChat([], max_rounds=3)
