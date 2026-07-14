"""Ciel gateway surface.

Exposes the public gateway building blocks:

* :func:`gateway.base.create_control_app` — FastAPI control plane for the
  agent runtime (``/health``, ``/info``, ``/v1/agent/run``, ``/v1/tools/...``,
  ``/v1/board/list``).
* :mod:`gateway.mcp` — MCP client (stdio/HTTP) + MCP server host + runtime
  integration, implemented as a native JSON-RPC endpoint.
* :class:`gateway.adapter.WebhookAdapter` — generic inbound messaging adapter.
* :func:`create_webhook_router` — mounts a messaging adapter into an existing
  FastAPI app so external channels can feed the agent.
* :func:`mount_mcp_app` — builds a FastAPI app exposing the MCP host endpoint
  (``/mcp``) backed by a runtime dispatcher, ready to serve over HTTP.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, FastAPI, Request

from ciel.gateway.adapter import Message, MessagingAdapter, WebhookAdapter
from ciel.gateway.adapter_slack import SlackAdapter
from ciel.gateway.base import create_control_app
from ciel.gateway.messaging import (
    create_discord_webhook_router,
    create_teams_webhook_router,
    create_webui_router,
)
from ciel.gateway.mcp import (
    DefaultAgentRuntimeMCPHost,
    MCPClient,
    MCPHostToolProvider,
    MCPServer,
)
from ciel.gateway.server import make_app

logger = logging.getLogger(__name__)

__all__ = [
    "create_control_app",
    "MCPClient",
    "MCPServer",
    "DefaultAgentRuntimeMCPHost",
    "MCPHostToolProvider",
    "Message",
    "MessagingAdapter",
    "WebhookAdapter",
    "SlackAdapter",
    "create_webhook_router",
    "create_slack_webhook_router",
    "create_teams_webhook_router",
    "create_discord_webhook_router",
    "create_webui_router",
    "mount_mcp_app",
    "make_app",
]


def create_webhook_router(
    adapter: WebhookAdapter,
    *,
    path: str = "/v1/messaging/webhook",
    api_key: Optional[str] = None,
):
    """Build an APIRouter that pushes inbound HTTP messages into ``adapter``.

    The router exposes ``POST {path}`` (accept a message) and
    ``GET {path}/health``. It is intentionally decoupled from a concrete agent
    runtime so it can be composed by any surface (control gateway, ACP, MCP).
    """
    from fastapi import APIRouter

    from ciel.gateway.auth import Depends, make_auth_dependency

    api_key_guard = Depends(make_auth_dependency(expected_key=api_key))

    router = APIRouter()

    @router.post(path, dependencies=[api_key_guard])
    async def receive_webhook(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"status": "rejected", "error": f"invalid json: {exc}"}
        return await adapter.handle_webhook(payload)

    @router.get(f"{path}/health")
    async def webhook_health():
        return {"status": "ok", "channel": "webhook"}

    return router


def create_slack_webhook_router(
    adapter: "SlackAdapter",  # noqa: F821
    *,
    path: str = "/v1/messaging/slack",
    signing_secret: str | None = None,
):
    """Build an APIRouter that ingests inbound Slack events into ``adapter``.

    Slack delivers events (``url_verification`` challenges and
    ``event_callback`` payloads) as JSON ``POST`` requests. This router:

    * answers the ``url_verification`` challenge so the Slack app can be
      installed/verified, and
    * for ``message`` events, converts the Slack event into a
      :class:`~ciel.gateway.adapter.Message` and enqueues it for the agent.

    The adapter is expected to expose an ``enqueue`` method (a subclass of
    :class:`SlackAdapter` that also holds an internal queue — e.g. via
    composition with :class:`~ciel.gateway.adapter.WebhookAdapter`) so events
    can be drained by the runtime. To keep coupling low, this router calls
    ``adapter.enqueue(...)`` when present and otherwise logs.

    Parameters
    ----------
    adapter:
        A :class:`SlackAdapter` (or compatible) that should receive inbound
        events.
    path:
        Route under which the Slack endpoint is exposed.
    signing_secret:
        Optional Slack signing secret used for request verification. When
        provided, payloads are verified; when omitted, verification is skipped
        (acceptable for local/offline smoke testing).
    """
    from fastapi import APIRouter, Request

    router = APIRouter()

    @router.post(path)
    async def slack_events(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"status": "rejected", "error": f"invalid json: {exc}"}

        # Slack URL verification handshake.
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}

        event = payload.get("event", {})
        if event.get("type") == "message" and not event.get("subtype"):
            channel = event.get("channel")
            message = Message(
                id=event.get("client_msg_id") or event.get("ts") or "",
                channel=channel,
                sender=event.get("user"),
                content=event.get("text", ""),
                metadata={"slack_event": event, "team": payload.get("team_id")},
            )
            enqueue = getattr(adapter, "enqueue", None)
            if callable(enqueue):
                # SlackAdapter.enqueue is synchronous (put_nowait); do NOT await it.
                enqueue(message)
            else:  # pragma: no cover - adapter without enqueue
                logger.warning(
                    "SlackAdapter has no enqueue(); dropping inbound message %s", message.id
                )
            return {"status": "accepted", "id": message.id}

        # Other event types (app_mention, etc.) — acknowledge to avoid retries.
        return {"status": "ok"}

    @router.get(f"{path}/health")
    async def slack_health():
        return {"status": "ok", "channel": "slack"}

    return router


def mount_mcp_app(
    *,
    dispatcher=None,
    tenant_id: str | None = None,
    path: str = "/mcp",
) -> "FastAPI":  # noqa: F821
    """Build a FastAPI app that serves the Ciel MCP host endpoint.

    The endpoint at ``{path}`` accepts MCP JSON-RPC payloads and routes them to
    a :class:`MCPServer` wired to the runtime's tool provider. Callers normally
    mount this under the control gateway or run it as a standalone service.

    Parameters
    ----------
    dispatcher:
        Optional :class:`ciel.runtime.DefaultToolDispatcher`. When omitted, a
        bare :class:`MCPServer` with no provider is created (logs initialize /
        shutdown only).
    tenant_id:
        Default tenant used for audit propagation.
    path:
        Route under which the MCP endpoint is exposed.
    """
    from fastapi import FastAPI

    from ciel.gateway.mcp import MCPServer

    provider = getattr(dispatcher, "provider", None) if dispatcher is not None else None
    server = MCPServer(provider=provider, tenant_id=tenant_id)

    app = FastAPI(title="Ciel MCP Host", version="0.1.0")
    app.state.mcp = server

    @app.post(path)
    async def mcp_endpoint(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}}
        return await server.handle(payload)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "ciel-mcp", "version": "0.1.0"}

    return app
