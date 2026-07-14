from __future__ import annotations

import json
import logging
from typing import Any, Dict, Mapping, Optional

from ciel.observability import AuditEvent, NullAuditSink, propagate
from ciel.runtime import ToolProvider, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class MCPError(Exception):
    def __init__(self, *, code: int, message: str, data: Optional[Any] = None) -> None:
        self.code = code
        super().__init__(message)
        self.data = data
        self.message = message


class MCPServer:
    """Minimal MCP-style JSON-RPC endpoint with tenant-aware handlers."""

    def __init__(
        self,
        *,
        provider: Optional[ToolProvider] = None,
        tenant_id: Optional[str] = None,
        audit_sink: Optional[Any] = None,
    ) -> None:
        self.provider = provider
        self.tenant_id = tenant_id
        self.audit_sink = audit_sink or NullAuditSink()
        self.handlers: Dict[str, Any] = {
            "initialize": self.handle_initialize,
            "shutdown": self.handle_shutdown,
            "tools/list": self.handle_tools_list,
            "tools/call": self.handle_tools_call,
        }

    async def handle(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        method = payload.get("method")
        request_id = payload.get("id")
        if method not in self.handlers:
            return self._error(request_id, -32601, "Method not found")
        try:
            result = await self.handlers[method](payload.get("params", {}))
        except Exception as exc:  # pragma: no cover - defensive path
            logger.exception("MCP handler error")
            return self._error(request_id, -32603, str(exc))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = params.get("tenant_id") or self.tenant_id
        self.tenant_id = tenant_id
        event = AuditEvent(
            event="mcp.server.initialize",
            data={
                "clientName": params.get("clientName"),
                "clientVersion": params.get("clientVersion"),
            },
        )
        normalized = propagate(event, tenant_id=tenant_id)
        await self.audit_sink.write(normalized)
        return {"status": "initialized", "version": "0.1.0", "tenant_id": tenant_id}

    async def handle_shutdown(self, params: Dict[str, Any]) -> Dict[str, Any]:
        event = AuditEvent(event="mcp.server.shutdown")
        normalized = propagate(event, tenant_id=self.tenant_id)
        await self.audit_sink.write(normalized)
        return {"status": "shutdown"}

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        toolset = params.get("toolset") or "default"
        tenant_id = params.get("tenant_id") or self.tenant_id
        specs: Sequence[ToolSpec] = ()
        if self.provider is not None:
            specs = await self.provider.tool_specs(tenant_id, toolset)
        return {"tools": [self._serialize_spec(spec) for spec in specs]}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.provider is None:
            return {"error": {"code": -32000, "message": "no tool provider configured"}}
        toolset = params.get("toolset") or "default"
        tenant_id = params.get("tenant_id") or self.tenant_id
        call_id = params.get("id") or params.get("tool_call_id") or str(uuid.uuid4())
        result = await self.provider.execute(
            tenant_id=tenant_id,
            toolset=toolset,
            name=params["name"],
            arguments=params.get("arguments") or {},
            tool_call_id=call_id,
        )
        response: Dict[str, Any] = {
            "id": result.id,
            "name": result.name,
            "output": result.output,
            "metadata": dict(result.metadata),
        }
        if result.error:
            response["error"] = result.error
        return response

    def _serialize_spec(self, spec: ToolSpec) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": spec.name,
            "description": spec.description,
            "parameters": dict(spec.parameters),
        }
        if spec.strict:
            payload["strict"] = spec.strict
        if spec.metadata:
            payload["metadata"] = dict(spec.metadata)
        return payload

    @staticmethod
    def _error(request_id: Optional[Any], code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
