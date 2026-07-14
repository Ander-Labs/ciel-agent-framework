from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

from ciel.common import CielError, TenantRequired
from ciel.observability import AuditEvent, InMemoryAuditSink, NullAuditSink, assert_tenant_event, propagate
from ciel.providers import ChatProvider, ProviderRegistry
from ciel.runtime import (
    AgentRuntimeResult,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DefaultToolDispatcher,
    ToolLoopResult,
    ToolProvider,
    ToolResult,
    ToolSpec,
)


@dataclass(frozen=True)
class AgentContext:
    agent: str
    session_id: str
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class DefaultAgentRuntime:
    """Concrete runtime wiring provider + tool execution with tracing."""

    def __init__(
        self,
        *,
        provider: ChatProvider,
        dispatcher: DefaultToolDispatcher,
        registry: Optional[ProviderRegistry] = None,
        audit_sink: Optional[Any] = None,
        agent: str = "default",
        approval_policy: Optional[Any] = None,
    ) -> None:
        self.provider = provider
        self.dispatcher = dispatcher
        self.registry = registry
        self.audit_sink = audit_sink or NullAuditSink()
        self.agent = agent
        self.approval_policy = approval_policy

    async def _emit(self, event: AuditEvent, *, tenant_id: Optional[str] = None) -> AuditEvent:
        normalized = propagate(event, tenant_id=tenant_id)
        await self.audit_sink.write(normalized)
        return normalized

    async def run_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AgentRuntimeResult:
        session_id = request.extra.get("session_id") or str(uuid.uuid4())
        context = AgentContext(agent=self.agent, session_id=session_id, tenant_id=tenant_id)
        await self._emit(
            AuditEvent(event="agent.loop.start", session_id=session_id, agent=self.agent, tenant_id=tenant_id),
            tenant_id=tenant_id,
        )

        messages: List[ChatMessage] = list(request.messages)
        loop_results: List[ToolLoopResult] = []
        turn_id = str(uuid.uuid4())
        finish_reason = "stop"

        response = await self.provider.complete(
            ChatRequest(
                messages=tuple(messages),
                tools=request.tools,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                extra={**request.extra, "session_id": session_id, "tenant_id": tenant_id},
            )
        )
        messages.append(response.choice.message)
        tool_calls = _extract_tool_calls(response)

        if tool_calls:
            dispatch_results: List[ToolResult] = []
            for call in tool_calls:
                call_arguments = call.get("arguments") or {}
                decision = None
                if self.approval_policy is not None and call.get("name") not in {None, ""}:
                    try:
                        from ciel.security import ApprovalRequest, ApprovalPolicy
                        if isinstance(self.approval_policy, type):
                            policy = self.approval_policy()
                        else:
                            policy = self.approval_policy
                        if hasattr(policy, "evaluate"):
                            decision = policy.evaluate(
                                ApprovalRequest(
                                    request_id=call.get("id") or call.get("tool_call_id") or str(uuid.uuid4()),
                                    actor=tenant_id or "unknown",
                                    tool=call.get("name", ""),
                                    arguments=call_arguments,
                                    risk="medium",
                                    tenant=tenant_id,
                                )
                            )
                    except Exception:
                        decision = None
                if decision is not None and not decision.approved:
                    dispatch_results.append(
                        ToolResult(
                            id=call.get("id") or call.get("tool_call_id") or str(uuid.uuid4()),
                            name=call.get("name", ""),
                            error=f"ApprovalDenied: {decision.note or 'denied'}",
                            metadata={"tenant_id": tenant_id, "approval_decision": decision.note or "denied"},
                        )
                    )
                    continue
                dispatch_results.append(
                    await self.dispatcher.dispatch(
                        tenant_id=tenant_id,
                        toolset=toolset or self.dispatcher.default_toolset or "default",
                        name=call.get("name", ""),
                        arguments=call_arguments,
                        tool_call_id=call.get("id") or call.get("tool_call_id") or str(uuid.uuid4()),
                    )
                )
            tool_turn = ToolLoopResult(
                turn_id=turn_id,
                messages=tuple(messages),
                tool_results=tuple(dispatch_results),
                finish_reason="tool_calls",
                tenant_id=tenant_id,
                metadata={"session_id": session_id, "toolset": toolset},
            )
            loop_results.append(tool_turn)
            finish_reason = "tool_calls"
            await self._emit(
                AuditEvent(
                    event="agent.tool_calls.dispatched",
                    session_id=session_id,
                    agent=self.agent,
                    tool_call_id=dispatch_results[0].id if dispatch_results else None,
                    data={"tools": [r.name for r in dispatch_results]},
                    tenant_id=tenant_id,
                ),
                tenant_id=tenant_id,
            )

        await self._emit(
            AuditEvent(event="agent.loop.end", session_id=session_id, agent=self.agent, tenant_id=tenant_id),
            tenant_id=tenant_id,
        )

        return AgentRuntimeResult(
            response=response,
            loop_results=tuple(loop_results),
            tenant_id=tenant_id,
            metadata={"session_id": session_id, "agent": self.agent},
        )

    async def stream_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AsyncIterator[ToolLoopResult]:
        result = await self.run_agent_loop(
            request=request,
            tenant_id=tenant_id,
            toolset=toolset,
            limit=limit,
        )
        for turn in result.loop_results:
            yield turn


def _extract_tool_calls(response: ChatResponse) -> List[Dict[str, Any]]:
    metadata = response.metadata or {}
    raw = metadata.get("tool_calls")
    if isinstance(raw, list):
        return raw
    message_tool_calls = getattr(response.choice.message, "tool_calls", None)
    if isinstance(message_tool_calls, list):
        return message_tool_calls
    return []
