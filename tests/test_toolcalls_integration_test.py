from __future__ import annotations

import pytest

from ciel.providers import ChatProvider
from ciel.runtime import (
    AgentRuntimeResult,
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    Tool,
    ToolProvider,
    ToolRegistry,
    ToolsetSchema,
    ToolSpec,
)


def _make_add_toolset() -> ToolRegistry:
    """Registry with a real callable 'add' tool in the 'default' toolset."""

    def add(arguments, *, tool_call_id="", tenant_id=None) -> int:
        return arguments["a"] + arguments["b"]

    registry = ToolRegistry(default_toolset="default")
    registry.register_toolset(
        ToolsetSchema(
            name="default",
            description="default tools",
            tools=(ToolSpec(name="add", description="Sum two integers", parameters={"type": "object"}),),
        )
    )
    registry.register_tool(
        "default",
        Tool(
            spec=ToolSpec(name="add", description="Sum two integers", parameters={"type": "object"}),
            callable_=add,
        ),
    )
    return registry


class FakeProviderMetadataToolCalls(ChatProvider):
    """Emits tool_calls inside response.metadata (ciel's native shape)."""

    provider_name = "fake-metadata"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=""),
                finish_reason="tool_calls",
            ),
            metadata={
                "tool_calls": [
                    {"id": "call_1", "name": "add", "arguments": {"a": 2, "b": 3}},
                ]
            },
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


class FakeProviderMessageToolCalls(ChatProvider):
    """Emits tool_calls inside response.choice.message.tool_calls (OpenAI shape)."""

    provider_name = "fake-message"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {"id": "call_2", "name": "add", "arguments": {"a": 4, "b": 6}},
                    ],
                ),
                finish_reason="tool_calls",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return (await self.complete(request),)

    async def models(self):
        return ()


@pytest.mark.asyncio
async def test_function_calling_metadata_tool_calls_executes_real_tool() -> None:
    registry = _make_add_toolset()
    provider = ToolProvider(registry=registry)
    dispatcher = DefaultToolDispatcher(provider, default_toolset="default")
    runtime = DefaultAgentRuntime(
        provider=FakeProviderMetadataToolCalls(),
        dispatcher=dispatcher,
        approval_policy=None,
    )

    request = ChatRequest(messages=(ChatMessage(role="user", content="add 2 and 3"),))
    result: AgentRuntimeResult = await runtime.run_agent_loop(
        request=request,
        tenant_id="tenant-1",
        toolset="default",
        limit=32,
    )

    assert len(result.loop_results) == 1
    assert result.loop_results[0].finish_reason == "tool_calls"
    assert len(result.loop_results[0].tool_results) == 1
    tool_result = result.loop_results[0].tool_results[0]
    assert tool_result.name == "add"
    assert tool_result.error is None
    assert tool_result.output == 5
    assert tool_result.metadata.get("tenant_id") == "tenant-1"
    assert result.tenant_id == "tenant-1"


@pytest.mark.asyncio
async def test_function_calling_message_tool_calls_executes_real_tool() -> None:
    registry = _make_add_toolset()
    provider = ToolProvider(registry=registry)
    dispatcher = DefaultToolDispatcher(provider, default_toolset="default")
    runtime = DefaultAgentRuntime(
        provider=FakeProviderMessageToolCalls(),
        dispatcher=dispatcher,
        approval_policy=None,
    )

    request = ChatRequest(messages=(ChatMessage(role="user", content="add 4 and 6"),))
    result: AgentRuntimeResult = await runtime.run_agent_loop(
        request=request,
        tenant_id="tenant-2",
        toolset="default",
        limit=32,
    )

    assert len(result.loop_results) == 1
    assert result.loop_results[0].finish_reason == "tool_calls"
    assert len(result.loop_results[0].tool_results) == 1
    tool_result = result.loop_results[0].tool_results[0]
    assert tool_result.name == "add"
    assert tool_result.error is None
    assert tool_result.output == 10
    assert tool_result.metadata.get("tenant_id") == "tenant-2"
