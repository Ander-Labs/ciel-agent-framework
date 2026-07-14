from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class AgentStep:
    id: str
    kind: str
    tool: Optional[str] = None
    prompt: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentSpec:
    name: str
    steps: Sequence[AgentStep]
    topology: str = "pipeline"
    budget: Dict[str, Any] = field(default_factory=lambda: {"max_tools": 8})
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "topology": self.topology,
            "budget": dict(self.budget),
            "steps": [
                {
                    "id": step.id,
                    "kind": step.kind,
                    "tool": step.tool,
                    "prompt": step.prompt,
                    "depends_on": list(step.depends_on),
                    "metadata": dict(step.metadata),
                }
                for step in self.steps
            ],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> AgentSpec:
        steps = [AgentStep(**item) for item in payload.get("steps", [])]
        return cls(
            name=payload.get("name", ""),
            steps=steps,
            topology=payload.get("topology", "pipeline"),
            budget=payload.get("budget", {}),
            metadata=payload.get("metadata", {}),
        )

    @classmethod
    def from_yaml(cls, payload: str) -> AgentSpec:
        import yaml

        data = yaml.safe_load(payload)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping")
        return cls.from_dict(data)


# Fase 5: orquestación best-of-breed (grafo de estado explícito + checkpoint,
# estilo LangGraph, montado sobre el Supervisor existente).
from ciel.orchestration.graph import (  # noqa: E402
    GraphApprovalDenied,
    GraphCheckpointStore,
    GraphEdge,
    GraphError,
    GraphNode,
    GraphPaused,
    GraphRunner,
    GraphState,
    NodeFn,
    StateGraph,
)
# Fase 5 (continuación): flows event-driven (CrewAI), group chat (AutoGen) y
# root agent con sub_agents (ADK) — todos montados sobre el Supervisor.
from ciel.orchestration.flows import (  # noqa: E402
    Flow,
    FlowCheckpointStore,
    FlowError,
    FlowRunner,
    FlowState,
    FlowStep,
)
from ciel.orchestration.chat import (  # noqa: E402
    Agent,
    ChatMessage,
    GroupChat,
    GroupChatCheckpointStore,
    GroupChatError,
    GroupChatManager,
    GroupChatState,
)
from ciel.orchestration.root import (  # noqa: E402
    RootAgent,
    RootAgentError,
    RootCheckpointStore,
    RootRunner,
    RootState,
    Specialist,
)
from ciel.orchestration.session import (  # noqa: E402
    SessionError,
    SessionStore,
)
# Fase 6 — Agencia autónoma en bucle (AutoGen/ADK): EventLoop durable +
# AutonomousAgent sobre Supervisor y SessionStore.
from ciel.orchestration.agent import (  # noqa: E402
    AgentError,
    AutonomousAgent,
    EventLoop,
    EventLoopCheckpointStore,
    EventLoopStep,
    Task,
    TaskError,
)

__all__ = [
    "AgentStep",
    "AgentSpec",
    "GraphCheckpointStore",
    "GraphEdge",
    "GraphError",
    "GraphNode",
    "GraphPaused",
    "GraphRunner",
    "GraphState",
    "GraphApprovalDenied",
    "NodeFn",
    "StateGraph",
    # flows (CrewAI)
    "Flow",
    "FlowCheckpointStore",
    "FlowError",
    "FlowRunner",
    "FlowState",
    "FlowStep",
    # chat (AutoGen)
    "Agent",
    "ChatMessage",
    "GroupChat",
    "GroupChatCheckpointStore",
    "GroupChatError",
    "GroupChatManager",
    "GroupChatState",
    # root (ADK)
    "RootAgent",
    "RootAgentError",
    "RootCheckpointStore",
    "RootRunner",
    "RootState",
    "Specialist",
    # session (ADK session state, cierre Fase 5)
    "SessionError",
    "SessionStore",
    # agent / event loop (Fase 6)
    "AgentError",
    "AutonomousAgent",
    "EventLoop",
    "EventLoopCheckpointStore",
    "EventLoopStep",
    "Task",
    "TaskError",
]
