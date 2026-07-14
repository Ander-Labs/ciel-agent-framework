"""Smoke test for the composed ``ciel serve`` gateway (three surfaces).

Verifies that :func:`ciel.gateway.server.make_app` composes control + MCP +
webhook on one app and that ``/health`` responds on each surface. Runtime/tool
requests still enforce tenant isolation (no relaxation of multi-tenancy).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ciel.gateway.server import make_app


def test_serve_composed_health_on_three_surfaces() -> None:
    app = make_app(tenant_id="acme")
    client = TestClient(app)

    # 1) control plane
    control = client.get("/health")
    assert control.status_code == 200
    assert control.json()["status"] == "ok"

    # 2) MCP host (mounted sub-app at /mcp)
    mcp = client.get("/mcp/health")
    assert mcp.status_code == 200
    assert mcp.json()["service"] == "ciel-mcp"

    # 3) webhook messaging router
    webhook = client.get("/v1/messaging/webhook/health")
    assert webhook.status_code == 200
    assert webhook.json()["channel"] == "webhook"


def test_serve_mcp_endpoint_lists_tools() -> None:
    app = make_app(tenant_id="acme")
    client = TestClient(app)
    resp = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"toolset": "default"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    # default toolset is empty here (offline echo provider), so no error is enough
    assert "result" in body


def test_serve_control_requires_tenant() -> None:
    app = make_app(tenant_id=None)
    client = TestClient(app)
    resp = client.post("/v1/agent/run", json={"prompt": "hi"})
    assert resp.status_code == 400
