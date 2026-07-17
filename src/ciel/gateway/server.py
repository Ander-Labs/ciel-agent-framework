"""Composed Ciel gateway application (control + MCP host + webhook).

:func:`make_app` builds a single FastAPI application that exposes the three
verified gateway surfaces on one port:

* control plane  -> :func:`ciel.gateway.base.create_control_app`
  (``/health``, ``/info``, ``/v1/agent/run``, ``/v1/tools/...``,
  ``/v1/board/list``)
* MCP host       -> :func:`ciel.gateway.mount_mcp_app` mounted at ``/mcp``
  (JSON-RPC ``POST /mcp/``)
* webhook        -> :func:`ciel.gateway.create_webhook_router` at
  ``/v1/messaging/webhook`` (``POST`` + ``/health``)

The runtime is built from environment configuration so ``ciel serve`` can
start with zero external dependencies: when no ``CIEL_PROVIDER_URL`` is set a
local echo provider is used, which keeps the gateway bootable for smoke tests
and offline deployments. Multi-tenancy is never relaxed — the control plane
still requires ``tenant_id`` on runtime/tool requests.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI

from ciel import __version__
from ciel.gateway.adapter import WebhookAdapter
from ciel.gateway.base import create_control_app
from ciel.runtime import (
    ChatChoice,
    ChatMessage,
    ChatResponse,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolRegistry,
)

logger = logging.getLogger(__name__)


class _EchoProvider:
    """Offline provider used when no remote LLM endpoint is configured.

    It returns an ``echo:<prompt>`` completion so the gateway can boot and
    serve health/tool endpoints without network access. It is intentionally
    deterministic and never makes outbound calls.
    """

    provider_name = "echo"

    async def complete(self, request) -> ChatResponse:
        prompt = request.messages[-1].content if request.messages else ""
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=f"echo:{prompt}"),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request):  # pragma: no cover - parity with runtime contract
        return (await self.complete(request),)

    async def models(self):  # pragma: no cover - not exercised by gateway
        from ciel.providers import ModelInfo

        return [ModelInfo(id="echo", provider=self.provider_name)]


def _build_chat_provider() -> object:
    provider_url = os.getenv("CIEL_PROVIDER_URL")
    if provider_url:
        from ciel.providers import OpenAICompatibleProvider

        logger.info("ciel serve: using remote provider %s", provider_url)
        return OpenAICompatibleProvider(
            base_url=provider_url,
            api_key=os.getenv("CIEL_API_KEY"),
            default_model=os.getenv("CIEL_MODEL"),
        )
    logger.info("ciel serve: no CIEL_PROVIDER_URL set; booting with offline echo provider")
    return _EchoProvider()


def make_app(
    *,
    tenant_id: Optional[str] = None,
    include_mcp: bool = True,
    include_webhook: bool = True,
) -> FastAPI:
    """Compose the full Ciel gateway into a single FastAPI app.

    Parameters
    ----------
    tenant_id:
        Default tenant propagated to the runtime when a request omits its own
        ``tenant_id``. Falls back to the ``CIEL_TENANT`` environment variable.
    include_mcp:
        Mount the MCP host app at ``/mcp``.
    include_webhook:
        Mount the webhook messaging router at ``/v1/messaging/webhook``.
    """
    tenant_id = tenant_id or os.getenv("CIEL_TENANT")

    # --- runtime wiring ----------------------------------------------------
    chat_provider = _build_chat_provider()
    registry = ToolRegistry(default_toolset="default")
    tool_provider = ToolProvider(registry=registry, require_tenant_on_execution=True)
    dispatcher = DefaultToolDispatcher(provider=tool_provider, default_toolset="default")
    runtime = DefaultAgentRuntime(provider=chat_provider, dispatcher=dispatcher)

    # Lazy import to avoid a circular import with the ``ciel.gateway`` package
    # (server.py is imported by gateway/__init__.py; the two helpers below are
    # defined there and only needed at call time, after the package is loaded).
    from ciel.gateway import create_webhook_router, mount_mcp_app

    # --- control plane (root app) -----------------------------------------
    app = create_control_app(runtime=runtime, registry=None, tenant_id=tenant_id)
    app.title = "Ciel Agent Framework Gateway"
    app.version = __version__

    # --- MCP host (mounted sub-application) -------------------------------
    if include_mcp:
        # Expose the JSON-RPC endpoint at the mount root so the resulting route
        # is ``POST /mcp/`` and health at ``GET /mcp/health``.
        mcp_app = mount_mcp_app(dispatcher=dispatcher, tenant_id=tenant_id, path="/")
        app.mount("/mcp", mcp_app)
        app.state.mcp_mounted = True
    else:
        app.state.mcp_mounted = False

    # --- webhook messaging adapter ----------------------------------------
    if include_webhook:
        adapter = WebhookAdapter()
        app.include_router(create_webhook_router(adapter))
        app.state.webhook_adapter = adapter

    # --- Fase 8: adapters de canal Teams/Discord/Web UI (offline-safe) -----
    # Se montan solo si no estamos en modo ultra-ligero (siempre por defecto).
    # Cada router enqueuea eventos entrantes en su adapter; el runtime los
    # consume vía ``adapter.receive()``. No requieren red para arrancar.
    try:
        from ciel.adapters import DiscordAdapter, TeamsAdapter, WebUIAdapter
        from ciel.gateway.messaging import (
            create_discord_webhook_router,
            create_teams_webhook_router,
            create_webui_router,
        )

        teams_adapter = TeamsAdapter(webhook_url=os.getenv("CIEL_TEAMS_WEBHOOK"))
        discord_adapter = DiscordAdapter(webhook_url=os.getenv("CIEL_DISCORD_WEBHOOK"))
        webui_adapter = WebUIAdapter()
        app.include_router(create_teams_webhook_router(teams_adapter))
        app.include_router(create_discord_webhook_router(discord_adapter))
        app.include_router(create_webui_router(webui_adapter))
        app.state.teams_adapter = teams_adapter
        app.state.discord_adapter = discord_adapter
        app.state.webui_adapter = webui_adapter
        logger.info("ciel serve: mounted Teams/Discord/WebUI messaging routers")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ciel serve: channel adapters not mounted: %s", exc)

    # --- Fase 13 / F19: Ciel Studio dashboard (offline-safe) --------
    # Expone /v1/studio con el snapshot de sesiones/loops. Usa el store
    # singleton de studio (compartido con install_studio_support).
    try:
        from ciel.studio import create_studio_router, get_studio_store

        studio_store = get_studio_store()
        app.include_router(create_studio_router(store=studio_store))
        app.state.studio_store = studio_store
        logger.info("ciel serve: mounted Ciel Studio dashboard at /v1/studio")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ciel serve: Ciel Studio not mounted: %s", exc)

    # --- Fase 13 / F20: Ciel Studio graph trace + replay ------------
    try:
        from ciel.studio_trace import create_trace_router, get_trace_store

        trace_store = get_trace_store()
        app.include_router(create_trace_router(store=trace_store))
        app.state.trace_store = trace_store
        logger.info("ciel serve: mounted Ciel Studio trace at /v1/studio/trace")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ciel serve: Ciel Studio trace not mounted: %s", exc)

    # --- Fase 13 / F21: Ciel Studio cost dashboard -------------------
    try:
        from ciel.studio_cost import create_cost_router, get_cost_store

        cost_store = get_cost_store()
        app.include_router(create_cost_router(store=cost_store))
        app.state.cost_store = cost_store
        logger.info("ciel serve: mounted Ciel Studio cost at /v1/studio/cost")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ciel serve: Ciel Studio cost not mounted: %s", exc)

    # --- Prometheus /metrics endpoint (lenient) --------------------------
    # Only mounted when prometheus-client is available; otherwise the import
    # is skipped so the gateway still boots offline.
    try:
        from ciel.observability.metrics import PROM_AVAILABLE, metrics_handler

        if PROM_AVAILABLE:
            app.add_api_route(
                "/metrics", metrics_handler, methods=["GET"], include_in_schema=False
            )
            app.state.metrics_mounted = True
            logger.info("ciel serve: mounted /metrics (Prometheus)")
        else:  # pragma: no cover - depends on optional extra
            app.state.metrics_mounted = False
            logger.info("ciel serve: /metrics not mounted (prometheus-client absent)")
    except Exception as exc:  # pragma: no cover - defensive
        app.state.metrics_mounted = False
        logger.warning("ciel serve: /metrics mount skipped: %s", exc)

    return app


__all__ = ["make_app", "_EchoProvider"]
