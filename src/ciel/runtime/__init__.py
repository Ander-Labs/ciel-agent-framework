from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence, Type, Union

from ciel.common import CielError, TenantRequired
from ciel.observability import AuditEvent, InMemoryAuditSink, NullAuditSink, assert_tenant_event, propagate
from ciel.providers import ChatProvider, ProviderRegistry
from ciel.runtime.tools import (
    Tool,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    ToolsetSchema,
)


@dataclass(frozen=True)
class ToolProvider:
    registry: ToolRegistry
    require_tenant_on_execution: bool = True

    async def tool_specs(self, tenant_id: Optional[str], toolset: str) -> Sequence[ToolSpec]:
        return tuple(getattr(self.registry, "_toolsets", {}).get(toolset, ToolsetSchema(name=toolset, description="")).tools)

    async def execute(
        self,
        *,
        tenant_id: Optional[str],
        toolset: Optional[str],
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> ToolResult:
        target_toolset = toolset or (self.registry.default_toolset or "default")
        if self.require_tenant_on_execution and not tenant_id:
            raise TenantRequired(f"tenant_id is required to execute tool '{name}' in toolset '{target_toolset}'.")
        tool = self.registry.get_tool(toolset=target_toolset, name=name)
        if tool is None:
            return ToolResult(id=tool_call_id, name=name, error=f"unknown tool: {target_toolset}.{name}", metadata={"tenant_id": tenant_id})
        if getattr(tool, "required_tenant", False) and not tenant_id:
            raise TenantRequired(f"tool '{name}' requires tenant_id, but none was provided.")
        if tool.callable_ is None:
            output = {"arguments": arguments, "description": tool.spec.description}
            return ToolResult(id=tool_call_id, name=name, output=output, metadata={"tenant_id": tenant_id})
        # Official tool callable contract:
        #   callable_(arguments: dict, *, tool_call_id: str, tenant_id: str | None) -> ToolResult | dict | Any
        try:
            result = tool.callable_(arguments, tool_call_id=tool_call_id, tenant_id=tenant_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — surface tool errors as ToolResult
            return ToolResult(id=tool_call_id, name=name, error=f"{type(exc).__name__}: {exc}", metadata={"tenant_id": tenant_id})
        if isinstance(result, ToolResult):
            if not result.metadata.get("tenant_id"):
                result.metadata["tenant_id"] = tenant_id
            return result
        return ToolResult(id=tool_call_id, name=name, output=result, metadata={"tenant_id": tenant_id})


class StaticToolProvider(ToolProvider):
    def __init__(self, tools: Mapping[str, Sequence[ToolSpec]], *, require_tenant: bool = False) -> None:
        registry = ToolRegistry(default_toolset="default")
        for toolset, values in tools.items():
            registry.register_toolset(
                ToolsetSchema(
                    name=toolset,
                    description="",
                    tools=tuple(values) if not isinstance(values, tuple) else values,
                    require_tenant=require_tenant,
                )
            )
        super().__init__(registry=registry, require_tenant_on_execution=require_tenant)


class DefaultToolDispatcher:
    """Dispatch tool requests to a configured ToolProvider."""

    provider: ToolProvider
    default_toolset: Optional[str]

    def __init__(self, provider: ToolProvider, default_toolset: Optional[str] = None) -> None:
        self.provider = provider
        self.default_toolset = default_toolset or getattr(provider.registry, "default_toolset", None)

    async def dispatch(
        self,
        *,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> ToolResult:
        result = await self.provider.execute(
            tenant_id=tenant_id,
            toolset=toolset or self.default_toolset or "default",
            name=name,
            arguments=arguments,
            tool_call_id=tool_call_id,
        )
        result.metadata.setdefault("tenant_id", tenant_id)
        return result

    async def dispatch_all(
        self,
        *,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        calls: Sequence[Dict[str, Any]],
    ):
        results: List[ToolResult] = []
        for call in calls:
            call_tenant_id = tenant_id or call.get("metadata", {}).get("tenant_id")
            results.append(
                await self.dispatch(
                    tenant_id=call_tenant_id,
                    toolset=toolset or self.default_toolset or "default",
                    name=call["name"],
                    arguments=call.get("arguments", {}),
                    tool_call_id=call.get("id") or call.get("tool_call_id") or str(uuid.uuid4()),
                )
            )
        return results


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatChoice:
    message: ChatMessage
    finish_reason: str
    usage: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatRequest:
    messages: Sequence[ChatMessage]
    tools: Sequence[ToolSpec] = ()
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    choice: ChatChoice
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelProvider:
    """Model/provider contract for completions."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:
        raise NotImplementedError


@dataclass(frozen=True)
class ToolLoopResult:
    turn_id: str
    messages: Sequence[ChatMessage]
    tool_results: Sequence[ToolResult]
    finish_reason: str
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeResult:
    response: ChatResponse
    loop_results: Sequence[ToolLoopResult]
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    agent: str
    session_id: str
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentRuntime:
    """Async runtime contract for tool-loop execution and streaming."""

    async def run_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AgentRuntimeResult:
        raise NotImplementedError

    async def stream_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AsyncIterator[ToolLoopResult]:
        raise NotImplementedError


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
                        decision = self.approval_policy.evaluate(
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

    async def stream_tokens(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream incremental assistant tokens from the provider.

        Calls ``provider.stream`` (real SSE streaming) and re-emits the
        partial ``content`` of each incremental :class:`ChatResponse` as it
        arrives, so callers see the answer grow token by token.
        """
        chunks = await self.provider.stream(request=request)
        prior = ""
        for chunk in chunks:
            content = chunk.choice.message.content or ""
            if content != prior:
                yield content
                prior = content


def _extract_tool_calls(response: ChatResponse) -> List[Dict[str, Any]]:
    metadata = response.metadata or {}
    raw = metadata.get("tool_calls")
    if isinstance(raw, list):
        return raw
    message_tool_calls = getattr(response.choice.message, "tool_calls", None)
    if isinstance(message_tool_calls, list):
        return message_tool_calls
    return []
