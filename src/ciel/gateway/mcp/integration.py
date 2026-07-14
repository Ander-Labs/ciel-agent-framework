from __future__ import annotations

import json
import logging
from typing import Any, Dict, Mapping, Optional, Sequence

from ciel.observability import AuditEvent, InMemoryAuditSink, NullAuditSink, propagate
from ciel.runtime import ToolProvider, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


from ciel.gateway.mcp.server import MCPServer


class MCPHostToolProvider(ToolProvider):
    """Expose an MCP server as a Ciel ToolProvider."""

    def __init__(self, server: Any, *, default_toolset: str = "default") -> None:
        self.server = server
        self.default_toolset = default_toolset

    async def tool_specs(self, toolset: str) -> Sequence[ToolSpec]:
        payload = await self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"toolset": toolset or self.default_toolset}}
        )
        result = payload.get("result") or {}
        specs = []
        for spec in result.get("tools", []):
            specs.append(
                ToolSpec(
                    name=spec.get("name", ""),
                    description=spec.get("description", ""),
                    parameters=spec.get("parameters", {}),
                    strict=spec.get("strict", False),
                    metadata=spec.get("metadata", {}),
                )
            )
        return specs

    async def execute(
        self,
        *,
        tenant_id: Optional[str] = None,
        toolset: str,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> ToolResult:
        payload = await self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": tool_call_id,
                "method": "tools/call",
                "params": {
                    "id": tool_call_id,
                    "tenant_id": tenant_id,
                    "name": name,
                    "arguments": arguments,
                    "toolset": toolset or self.default_toolset,
                },
            }
        )
        result = payload.get("result") or {}
        return ToolResult(
            id=result.get("id", tool_call_id),
            name=name,
            output=result.get("output"),
            error=(result.get("error") or {}).get("message") if isinstance(result.get("error"), dict) else result.get("error"),
            metadata=result.get("metadata", {}),
        )


class DefaultAgentRuntimeMCPHost:
    """Host DefaultAgentRuntime behavior through an MCP server boundary."""

    def __init__(
        self,
        runtime: Any,
        *,
        audit_sink: Optional[Any] = None,
        tenant_id: Optional[str] = None,
        agent: str = "default",
    ) -> None:
        self.runtime = runtime
        self.audit_sink = audit_sink or NullAuditSink()
        self.tenant_id = tenant_id
        self.agent = agent
        self.server = MCPServer(audit_sink=self.audit_sink, tenant_id=tenant_id)

    async def _emit(self, event: AuditEvent, *, tenant_id: Optional[str] = None) -> AuditEvent:
        normalized = propagate(event, tenant_id=tenant_id)
        await self.audit_sink.write(normalized)
        return normalized

    async def handle_request(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        response = await self.server.handle(payload)
        await self._emit(
            AuditEvent(
                event="mcp.host.request",
                agent=self.agent,
                data={"method": payload.get("method"), "request_id": payload.get("id")},
            ),
            tenant_id=self.tenant_id,
        )
        return response
