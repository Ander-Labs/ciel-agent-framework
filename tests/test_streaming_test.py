"""Deterministic tests for real SSE streaming in the OpenAI-compatible provider.

These tests never touch the network: they drive ``OpenAICompatibleProvider``
through an ``httpx.MockTransport`` that replays a Server-Sent Events body, and
verify that ``stream()`` yields growing incremental ``ChatResponse`` chunks and
that ``DefaultAgentRuntime.stream_tokens`` re-emits the partial content.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from ciel.providers import OpenAICompatibleProvider
from ciel.runtime import (
    ChatMessage,
    ChatRequest,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    StaticToolProvider,
    ToolLoopResult,
    ToolSpec,
)


def _sse_body(pieces: List[str]) -> bytes:
    lines = []
    for piece in pieces:
        event = {"choices": [{"delta": {"content": piece}, "finish_reason": None}]}
        lines.append("data: " + json.dumps(event))
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_provider(sse_body: bytes, tenant: str | None = "t1") -> OpenAICompatibleProvider:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("accept") == "text/event-stream"
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(_handler)
    provider = OpenAICompatibleProvider(base_url="http://mock/v1", api_key="k", default_model="m", tenant=tenant)
    # Inject the mock transport by replacing the client factory context.
    provider._mock_transport = transport  # type: ignore[attr-defined]
    return provider


@pytest.mark.asyncio
async def test_stream_produces_growing_incremental_responses() -> None:
    pieces = ["Hello", ", this", " is", " a streamed", " response."]
    provider = _make_provider(_sse_body(pieces))

    # Patch the AsyncClient used inside stream() to use our mock transport.
    original_client = httpx.AsyncClient

    def _mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = provider._mock_transport  # type: ignore[attr-defined]
        return original_client(*args, **kwargs)

    httpx.AsyncClient = _mock_client  # type: ignore[assignment]
    try:
        chunks = await provider.stream(request=ChatRequest(messages=(ChatMessage(role="user", content="Say hello."),)))
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]

    assert len(chunks) == len(pieces)
    contents = [c.choice.message.content for c in chunks]
    assert contents == ["Hello", "Hello, this", "Hello, this is", "Hello, this is a streamed", "Hello, this is a streamed response."]
    # Final chunk must equal concatenation of all pieces.
    assert contents[-1] == "".join(pieces)
    # tenant propagated in metadata
    assert chunks[0].metadata.get("tenant") == "t1"


@pytest.mark.asyncio
async def test_stream_no_tenant_yields_none_metadata() -> None:
    pieces = ["Hi", " there"]
    provider = _make_provider(_sse_body(pieces), tenant=None)

    original_client = httpx.AsyncClient

    def _mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = provider._mock_transport  # type: ignore[attr-defined]
        return original_client(*args, **kwargs)

    httpx.AsyncClient = _mock_client  # type: ignore[assignment]
    try:
        chunks = await provider.stream(request=ChatRequest(messages=(ChatMessage(role="user", content="Hi."),)))
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]

    assert len(chunks) == 2
    assert chunks[-1].choice.message.content == "Hi there"
    assert chunks[0].metadata.get("tenant") is None


@pytest.mark.asyncio
async def test_stream_tokens_reemits_growing_content() -> None:
    pieces = ["Uno", " dos", " tres"]
    provider = _make_provider(_sse_body(pieces), tenant="t2")

    tools = (
        ToolSpec(name="echo", description="echo", parameters={"type": "object", "properties": {}}, metadata={}),
    )
    dispatcher = DefaultToolDispatcher(provider=StaticToolProvider(tools={"demo": tools}), default_toolset="demo")
    runtime = DefaultAgentRuntime(provider=provider, dispatcher=dispatcher, agent="default", approval_policy=None)

    original_client = httpx.AsyncClient

    def _mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = provider._mock_transport  # type: ignore[attr-defined]
        return original_client(*args, **kwargs)

    httpx.AsyncClient = _mock_client  # type: ignore[assignment]
    try:
        emitted = [tok async for tok in runtime.stream_tokens(
            request=ChatRequest(messages=(ChatMessage(role="user", content="Cuenta."),)),
            tenant_id="t2",
        )]
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]

    assert emitted == ["Uno", "Uno dos", "Uno dos tres"]


class _ToolCallProvider(OpenAICompatibleProvider):
    """Provider stub that returns a single assistant turn requesting a tool."""

    def __init__(self, *, tool_name: str, tenant: str | None = "t1") -> None:
        super().__init__(base_url="http://mock/v1", api_key="k", default_model="m", tenant=tenant)
        self._tool_name = tool_name

    async def complete(self, request: ChatRequest) -> ChatResponse:
        from ciel.runtime import ChatMessage, ChatResponse, ChatChoice

        message = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "call_1", "name": self._tool_name, "arguments": {"x": 1}, "type": "function"}
            ],
            metadata={"tool_calls": [
                {"id": "call_1", "name": self._tool_name, "arguments": {"x": 1}, "type": "function"}
            ]},
        )
        return ChatResponse(choice=ChatChoice(message=message, finish_reason="tool_calls"))


@pytest.mark.asyncio
async def test_stream_agent_loop_yields_tool_turn() -> None:
    tools = (
        ToolSpec(name="add", description="adds", parameters={"type": "object", "properties": {}}, metadata={}),
    )
    provider = _ToolCallProvider(tool_name="add", tenant="t1")
    dispatcher = DefaultToolDispatcher(provider=StaticToolProvider(tools={"demo": tools}), default_toolset="demo")
    runtime = DefaultAgentRuntime(provider=provider, dispatcher=dispatcher, agent="default", approval_policy=None)

    turns = [
        turn
        async for turn in runtime.stream_agent_loop(
            request=ChatRequest(messages=(ChatMessage(role="user", content="Suma."),)),
            tenant_id="t1",
            toolset="demo",
        )
    ]

    assert len(turns) == 1
    turn = turns[0]
    assert isinstance(turn, ToolLoopResult)
    assert turn.finish_reason == "tool_calls"
    assert len(turn.tool_results) == 1
    assert turn.tool_results[0].name == "add"
    # StaticToolProvider echoes the arguments it was called with.
    assert turn.tool_results[0].output == {"arguments": {"x": 1}, "description": "adds"}
    assert turn.tenant_id == "t1"


@pytest.mark.asyncio
async def test_stream_tokens_handles_empty_sse_body() -> None:
    # A body with no `data:` SSE lines must not crash: it yields nothing.
    provider = _make_provider(b"", tenant="t3")

    tools = (
        ToolSpec(name="echo", description="echo", parameters={"type": "object", "properties": {}}, metadata={}),
    )
    dispatcher = DefaultToolDispatcher(provider=StaticToolProvider(tools={"demo": tools}), default_toolset="demo")
    runtime = DefaultAgentRuntime(provider=provider, dispatcher=dispatcher, agent="default", approval_policy=None)

    original_client = httpx.AsyncClient

    def _mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = provider._mock_transport  # type: ignore[attr-defined]
        return original_client(*args, **kwargs)

    httpx.AsyncClient = _mock_client  # type: ignore[assignment]
    try:
        emitted = [tok async for tok in runtime.stream_tokens(
            request=ChatRequest(messages=(ChatMessage(role="user", content="Hola."),)),
            tenant_id="t3",
        )]
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]

    assert emitted == []
