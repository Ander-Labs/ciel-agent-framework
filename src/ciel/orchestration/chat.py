from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ciel.orchestration.supervisor import Supervisor, WorkerContext
from ciel.runtime.memory import MemoryStore


# Fase 5 — GroupChat estilo AutoGen.
#
# Agentes CONVERSABLES entre sí resuelven una tarea en diálogo. Separación
# limpia Agent / Model / Tool / GroupChat (AutoGen). El núcleo es modelo
# agnóstico: cada participante es una función ``responder(state) -> mensaje``
# que recibe el transcripto y devuelve su réplica. Esto lo hace OFFLINE-SAFE:
# los demos/cli usan funciones locales sobre ``state_data`` (sin red ni
# proveedor), pero un participante real puede llamar a ``ciel.runtime``.
#
# ``GroupChatManager`` orquesta: selecciona el siguiente hablante según una
# estrategia (round-robin o unselector explícito) y detiene cuando un
# participante emite una señal de ``terminate`` o se alcanza ``max_rounds``.

Message = Dict[str, Any]  # {"role": <agent_id>, "content": str, "round": int}
AgentFn = Callable[["GroupChatState"], Any]


@dataclass
class ChatMessage:
    """Mensaje del transcripto (estilo AutoGen ChatMessage simplificado)."""

    role: str
    content: str
    round: int = 0

    def to_dict(self) -> Message:
        return {"role": self.role, "content": self.content, "round": self.round}


@dataclass
class GroupChatState:
    """Estado compartido del group chat: transcripto + metadata por ronda."""

    transcript: List[ChatMessage] = field(default_factory=list)
    rounds: int = 0
    terminated: bool = False
    terminator: Optional[str] = None

    def last_message(self) -> Optional[ChatMessage]:
        return self.transcript[-1] if self.transcript else None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "transcript": [m.to_dict() for m in self.transcript],
            "rounds": self.rounds,
            "terminated": self.terminated,
            "terminator": self.terminator,
        }

    @classmethod
    def from_snapshot(cls, snap: Dict[str, Any]) -> "GroupChatState":
        return cls(
            transcript=[ChatMessage(**m) for m in snap.get("transcript", [])],
            rounds=int(snap.get("rounds", 0)),
            terminated=bool(snap.get("terminated", False)),
            terminator=snap.get("terminator"),
        )


class GroupChatError(Exception):
    pass


@dataclass
class Agent:
    """Participante conversable del group chat.

    ``responder`` recibe el ``GroupChatState`` y devuelve el texto de su
    réplica (o una corutina). Si ``terminate_if`` recibe el texto y devuelve
    True, ese mensaje finaliza la conversación.
    """

    name: str
    responder: AgentFn
    system_message: str = ""
    terminate_if: Optional[Callable[[str], bool]] = None

    async def _reply(self, state: GroupChatState) -> str:
        res = self.responder(state)
        if hasattr(res, "__await__"):
            return await res
        return res

    def _is_terminator(self, text: str) -> bool:
        if self.terminate_if is None:
            return False
        return bool(self.terminate_if(text))


class GroupChat:
    """Configuración del group chat (participantes + estrategia de turnos)."""

    def __init__(
        self,
        participants: List[Agent],
        *,
        max_rounds: int = 12,
        selector: Optional[Callable[["GroupChatState", List[Agent]], str]] = None,
        terminate_keyword: str = "TERMINATE",
    ) -> None:
        if not participants:
            raise GroupChatError("group chat requires at least one participant")
        self.participants = list(participants)
        self._by_name = {p.name: p for p in participants}
        self.max_rounds = max_rounds
        self.selector = selector
        self.terminate_keyword = terminate_keyword
        # round-robin a partir del índice 0
        self._next_index = 0

    def participant_names(self) -> List[str]:
        return [p.name for p in self.participants]

    def get(self, name: str) -> Agent:
        if name not in self._by_name:
            raise GroupChatError(f"unknown participant '{name}'")
        return self._by_name[name]

    def select_next(self, state: GroupChatState) -> Agent:
        if self.selector is not None:
            name = self.selector(state, self.participants)
            return self.get(name)
        # round-robin determinista (estilo AutoGen default)
        agent = self.participants[self._next_index % len(self.participants)]
        self._next_index += 1
        return agent


class GroupChatManager:
    """Ejecuta el diálogo: selecciona hablante, recolecta réplica, evalúa
    terminación. Montado SOBRE ``Supervisor`` para heredar retry/timeout/budget
    por participante (cada réplica es un worker del supervisor)."""

    def __init__(
        self,
        chat: GroupChat,
        *,
        supervisor: Optional[Supervisor] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.chat = chat
        self.supervisor = supervisor or Supervisor()
        self.tenant_id = tenant_id
        self.session_id = session_id

    async def _reply_via_supervisor(self, agent: Agent, state: GroupChatState, round_no: int) -> str:
        async def _worker(ctx: WorkerContext) -> str:
            return await agent._reply(state)

        result = await self.supervisor.run(
            step_id=f"chat:{agent.name}:{round_no}",
            worker=_worker,
            payload={"agent": agent.name, "round": round_no},
            worker_id=agent.name,
        )
        if result.failed:
            raise GroupChatError(f"agent '{agent.name}' failed in round {round_no}: {result.error}")
        return str(result.output)

    async def run(self, *, initial_message: Optional[str] = None, initial_sender: Optional[str] = None) -> GroupChatState:
        state = GroupChatState()
        if initial_message and initial_sender:
            state.transcript.append(ChatMessage(role=initial_sender, content=initial_message, round=0))

        for round_no in range(1, self.chat.max_rounds + 1):
            speaker = self.chat.select_next(state)
            text = await self._reply_via_supervisor(speaker, state, round_no)
            msg = ChatMessage(role=speaker.name, content=text, round=round_no)
            state.transcript.append(msg)
            state.rounds = round_no

            if self.chat.terminate_keyword and self.chat.terminate_keyword in text:
                state.terminated = True
                state.terminator = speaker.name
                break
            if speaker._is_terminator(text):
                state.terminated = True
                state.terminator = speaker.name
                break

        if state.rounds >= self.chat.max_rounds and not state.terminated:
            # Se agotaron las rondas sin señal explícita: marca terminado por límite.
            state.terminated = True
            state.terminator = None
        return state


class GroupChatCheckpointStore:
    """Persistencia del transcripto de group chat sobre ``MemoryStore``."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def _key(self, run_id: str) -> str:
        return f"chat:{run_id}"

    def save(self, *, run_id: str, state: GroupChatState, tenant_id: Optional[str], session_id: Optional[str]) -> str:
        import uuid

        checkpoint_id = str(uuid.uuid4())
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id or run_id,
            key=self._key(run_id),
            value={"checkpoint_id": checkpoint_id, "run_id": run_id, "state": state.snapshot()},
        )
        return checkpoint_id

    def load(self, *, run_id: str, tenant_id: Optional[str], session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        payload = self.memory.get(tenant_id=tenant_id, session_id=session_id or run_id, key=self._key(run_id))
        return payload if isinstance(payload, dict) else None
