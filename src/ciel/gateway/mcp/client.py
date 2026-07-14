from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence

from ciel.gateway.mcp.transports import MCPTransport
from ciel.observability import AuditEvent, NullAuditSink, propagate

logger = logging.getLogger(__name__)


class MCPError(Exception):
    def __init__(self, *, code: int, message: str, data: Optional[Any] = None) -> None:
        self.code = code
        super().__init__(message)
        self.data = data
        self.message = message


class MCPClient:
    """MCP protocol client over an explicit transport tenant-aware runtime."""

    def __init__(
        self,
        *,
        transport: MCPTransport,
        tenant_id: Optional[str] = None,
        audit_sink: Optional[Any] = None,
        agent: str = "default",
    ) -> None:
        if audit_sink is None:
            audit_sink = NullAuditSink()
        self.transport = transport
        self.tenant_id = tenant_id
        self.audit_sink = audit_sink
        self.agent = agent
        self.server_version: Optional[str] = None

    def _request_id(self) -> str:
        return str(uuid.uuid4())

    async def _send(self, payload: Dict[str, Any]) -> None:
        await self.transport.send(payload)

    async def _receive(self) -> AsyncIterator[Dict[str, Any]]:
        async for message in self.transport.receive():
            yield message

    async def _emit(self, event: AuditEvent) -> AuditEvent:
        normalized = propagate(event, tenant_id=self.tenant_id)
        await self.audit_sink.write(normalized)
        return normalized

    async def initialize(
        self,
        *,
        client_name: str = "ciel-mcp-client",
        client_version: str = "0.1.0",
    ) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id(),
            "method": "initialize",
            "params": {
                "clientName": client_name,
                "clientVersion": client_version,
                "tenant_id": self.tenant_id,
            },
        }
        await self._send(payload)
        async for message in self._receive():
            result = message.get("result")
            if result and isinstance(result, dict):
                self.server_version = result.get("serverVersion") or result.get("version")
            break
        await self._emit(
            AuditEvent(
                event="mcp.client.initialize",
                agent=self.agent,
                data={"client": client_name, "clientVersion": client_version},
            )
        )
