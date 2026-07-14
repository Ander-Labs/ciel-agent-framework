"""Fase 4 tests: control gateway, MCP host/client, messaging adapter.

These tests use a *stub* chat provider (no real LLM call) so the gateway and
MCP surfaces can be exercised deterministically.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Sequence

import pytest
from fastapi.testclient import TestClient

from ciel.gateway.adapter import WebhookAdapter
from ciel.gateway.base import create_control_app
from ciel.gateway.mcp import MCPServer, MCPHostToolProvider
from ciel.providers import ProviderRegistry
from ciel.runtime import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    StaticToolProvider,
    Tool,
    ToolExecutionContext,
    ToolProvider,
    ToolRegistry,
    ToolsetSchema,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Stub provider (no network / no LLM)
# ---------------------------------------------------------------------------


class _StubProvider:
    provider_name = "stub"

    def __init__(self, *, default_model: str = "stub-model") -> None:
        self.default_model = default_model

    async def complete(self, request: ChatRequest) -> ChatResponse:
        prompt = request.messages[-1].content if request.messages else ""
        return ChatResponse(
            choice=ChatChoice(message=ChatMessage(role="assistant", content=f"echo:{prompt}"), finish_reason="stop"),
            metadata={},
        )

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:  # pragma: no cover
        return (await self.complete(request),)

    async def models(self):  # pragma: no cover
        from ciel.providers import ModelInfo

        return [ModelInfo(id=self.default_model, provider=self.provider_name)]


def _build_specs():
    def echo(ctx: ToolExecutionContext, **kwargs: Any) -> Any:
        return kwargs

    def add(ctx: ToolExecutionContext, a: float = 0, b: float = 0) -> Any:
        return a + b

    echo_spec = ToolSpec(name="echo", description="Echo args", parameters={"type": "object"})
    add_spec = ToolSpec(name="add", description="Sum", parameters={"type": "object"})
    registry = ToolRegistry(default_toolset="demo")
    # register_toolset populates the toolset schema (used for listing specs)
    registry.register_toolset(
        ToolsetSchema(name="demo", description="", tools=(echo_spec, add_spec))
    )
    # register_tool stores the callable-bearing Tool objects (used for exec)
    registry.register_tool("demo", Tool(spec=echo_spec, callable_=echo))
    registry.register_tool("demo", Tool(spec=add_spec, callable_=add))
    return registry


def _build_runtime(toolset: str = "demo") -> DefaultAgentRuntime:
    registry = _build_specs()
    provider = ToolProvider(registry=registry, require_tenant_on_execution=False)
    dispatcher = DefaultToolDispatcher(provider=provider, default_toolset=toolset)
    return DefaultAgentRuntime(provider=_StubProvider(), dispatcher=dispatcher)


# ---------------------------------------------------------------------------
# Control gateway
# ---------------------------------------------------------------------------


def test_control_app_health_and_info() -> None:
    runtime = _build_runtime()
    registry = ProviderRegistry()
    registry.register("stub", _StubProvider())  # type: ignore[arg-type]
    app = create_control_app(runtime=runtime, registry=registry, tenant_id="acme")
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["version"]
    info = client.get("/info").json()
    assert info["default_tenant"] == "acme"
    assert any(p["name"] == "stub" for p in info["providers"])


def test_control_app_agent_run() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime)
    client = TestClient(app)
    resp = client.post("/v1/agent/run", json={"prompt": "hello", "tenant_id": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "echo:hello"
    assert body["session_id"]


def test_control_app_agent_run_requires_tenant() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime)
    client = TestClient(app)
    resp = client.post("/v1/agent/run", json={"prompt": "hello"})
    assert resp.status_code == 400


def test_control_app_agent_run_stream_requires_tenant() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime)
    client = TestClient(app)
    resp = client.post("/v1/agent/run/stream", json={"prompt": "hello"})
    assert resp.status_code == 400


def test_control_app_agent_run_stream_sse() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime, tenant_id="acme")
    client = TestClient(app)
    resp = client.post("/v1/agent/run/stream", json={"prompt": "hello", "tenant_id": "acme"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "data:" in body
    assert "[DONE]" in body
    # El stub emite el contenido completo en un único evento.
    assert "data: echo:hello" in body


def test_control_app_agent_run_propagates_tenant() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime, tenant_id="acme")
    client = TestClient(app)
    resp = client.post("/v1/agent/run", json={"prompt": "hi", "tenant_id": "tenant-x"})
    assert resp.status_code == 200


def test_control_app_tool_invoke() -> None:
    runtime = _build_runtime()
    app = create_control_app(runtime=runtime)
    client = TestClient(app)
    resp = client.post("/v1/tools/demo/add", json={"arguments": {"a": 2, "b": 3}, "tenant_id": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "add"
    assert body["output"] == 5


def test_control_app_webhook_router_accepts_message() -> None:
    from ciel.gateway import create_webhook_router

    runtime = _build_runtime()
    app = create_control_app(runtime=runtime)
    adapter = WebhookAdapter()
    app.include_router(create_webhook_router(adapter))
    client = TestClient(app)
    resp = client.post(
        "/v1/messaging/webhook",
        json={"channel": "slack", "content": "ping", "sender": "u1"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    msg = asyncio.new_event_loop().run_until_complete(adapter.receive_internal())
    assert msg.channel == "slack"
    assert msg.content == "ping"


# ---------------------------------------------------------------------------
# MCP host (JSON-RPC server)
# ---------------------------------------------------------------------------


def test_mcp_server_lists_and_calls_tools() -> None:
    runtime = _build_runtime()
    dispatcher = runtime.dispatcher
    server = MCPServer(provider=dispatcher.provider, tenant_id="acme")
    init = asyncio.new_event_loop().run_until_complete(
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"tenant_id": "acme"}})
    )
    assert init["result"]["status"] == "initialized"

    listed = asyncio.new_event_loop().run_until_complete(
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"toolset": "demo"}})
    )
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names >= {"echo", "add"}

    called = asyncio.new_event_loop().run_until_complete(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 4, "b": 6}, "toolset": "demo", "id": "tc-1"},
            }
        )
    )
    assert called["result"]["output"] == 10


def test_mcp_host_tool_provider_bridge() -> None:
    runtime = _build_runtime()
    server = MCPServer(provider=runtime.dispatcher.provider, tenant_id="acme")
    provider = MCPHostToolProvider(server, default_toolset="demo")
    specs = asyncio.new_event_loop().run_until_complete(provider.tool_specs("demo"))
    assert {s.name for s in specs} >= {"echo", "add"}
    result = asyncio.new_event_loop().run_until_complete(
        provider.execute(toolset="demo", name="add", arguments={"a": 1, "b": 2}, tool_call_id="x")
    )
    assert result.output == 3


def test_mount_mcp_app_exposes_endpoint() -> None:
    from ciel.gateway import mount_mcp_app

    runtime = _build_runtime()
    app = mount_mcp_app(dispatcher=runtime.dispatcher, tenant_id="acme")
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["service"] == "ciel-mcp"
    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"toolset": "demo"}},
    ).json()
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names >= {"echo", "add"}


# ---------------------------------------------------------------------------
# Webhook adapter unit
# ---------------------------------------------------------------------------


def test_webhook_adapter_validation() -> None:
    adapter = WebhookAdapter()
    loop = asyncio.new_event_loop()
    rejected = loop.run_until_complete(adapter.handle_webhook({"content": "x"}))
    assert rejected["status"] == "rejected"
    accepted = loop.run_until_complete(adapter.handle_webhook({"channel": "c", "content": "hello"}))
    assert accepted["status"] == "accepted"
    assert "id" in accepted
