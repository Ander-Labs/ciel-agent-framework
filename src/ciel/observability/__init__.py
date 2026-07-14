from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence


@dataclass
class AuditEvent:
    event: str
    session_id: Optional[str] = None
    agent: Optional[str] = None
    tool_call_id: Optional[str] = None
    data: Dict[str, Any] = None
    tenant_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {}


class AuditSink:
    async def write(self, event: AuditEvent) -> None:
        raise NotImplementedError


class InMemoryAuditSink(AuditSink):
    def __init__(self) -> None:
        self.events: List[AuditEvent] = []

    async def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditSink(AuditSink):
    """JSONL audit sink partitioned by tenant and session.

    Each flushed event is written to ``base_path / tenant_id / session_id
    / {tenant_id}-{session_id}.jsonl``. Missing directories are created
    automatically and writes are protected by an internal lock to keep
    async consumers safe.
    """

    def __init__(self, base_path: Path | str = "audit") -> None:
        self.base_path = Path(base_path)
        self._lock = asyncio.Lock()

    def _jsonl_path(self, event: AuditEvent) -> Path:
        tenant = event.tenant_id or "_global"
        session = event.session_id or "_nosession"
        return self.base_path / tenant / session / f"{tenant}-{session}.jsonl"

    async def write(self, event: AuditEvent) -> None:
        path = self._jsonl_path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            f = await asyncio.to_thread(path.open, mode="a", encoding="utf-8")
            try:
                payload = {
                    "ts": time.time(),
                    "event": event.event,
                    "tenant_id": event.tenant_id,
                    "session_id": event.session_id,
                    "agent": event.agent,
                    "tool_call_id": event.tool_call_id,
                    "data": event.data or {},
                }
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
            finally:
                await asyncio.to_thread(f.close)


class NullAuditSink(AuditSink):
    async def write(self, event: AuditEvent) -> None:
        return


__all__ = ["AuditEvent", "AuditSink", "InMemoryAuditSink", "JsonlAuditSink", "NullAuditSink", "TraceSpan", "ToolAwareTracer", "assert_tenant_event", "propagate"]


def assert_tenant_event(event: AuditEvent) -> None:
    if event.tenant_id is None:
        raise ValueError("AuditEvent requires tenant_id for multi-tenancy tracing")


def propagate(event: AuditEvent, *, tenant_id: Optional[str] = None) -> AuditEvent:
    normalized_tenant_id = tenant_id or event.tenant_id
    if normalized_tenant_id is None:
        raise ValueError(
            "propagate() requires tenant_id to be passed explicitly or present on event"
        )
    if tenant_id is not None:
        event.tenant_id = normalized_tenant_id
    return event


@dataclass(frozen=True)
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    tenant_id: Optional[str] = None
    name: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    events: List[AuditEvent] = field(default_factory=list)

    def add_event(self, event: AuditEvent, *, tenant_id: Optional[str] = None) -> AuditEvent:
        normalized = propagate(event, tenant_id=tenant_id)
        normalized.data.setdefault("trace_id", self.trace_id)
        normalized.data.setdefault("span_id", self.span_id)
        self.events.append(normalized)
        return normalized

    @asynccontextmanager
    async def start_child(
        self, name: str, *, tenant_id: Optional[str] = None
    ) -> AsyncIterator["TraceSpan"]:
        child = TraceSpan(
            trace_id=self.trace_id,
            span_id=f"{self.span_id}.{name}",
            parent_span_id=self.span_id,
            tenant_id=tenant_id or self.tenant_id,
            name=name,
        )
        yield child


class ToolAwareTracer:
    """Tool-aware async tracer.

    Keeps lightweight session/tenant root spans and emits tool call spans
    through an async context manager. Every lifecycle event is written
    to the provided sink so sinks can aggregate cross-tool traces.
    """

    def __init__(self, sink: AuditSink) -> None:
        self.sink = sink
        self._spans: Dict[str, TraceSpan] = {}

    def span(self, trace_id: str, *, tenant_id: Optional[str] = None) -> TraceSpan:
        key = f"{tenant_id or '_'}:{trace_id}"
        if key not in self._spans:
            self._spans[key] = TraceSpan(
                trace_id=trace_id,
                span_id="root",
                tenant_id=tenant_id,
            )
        return self._spans[key]

    @asynccontextmanager
    async def tool_span(
        self,
        tool_name: str,
        *,
        trace_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[TraceSpan]:
        resolved_trace_id = trace_id or "trace"
        parent = self.span(trace_id=resolved_trace_id, tenant_id=tenant_id)
        async with parent.start_child(tool_name, tenant_id=tenant_id) as span:
            await self.sink.write(
                AuditEvent(
                    event="tool.call.start",
                    tenant_id=tenant_id,
                    tool_call_id=tool_call_id,
                    data={"arguments": arguments or {}, "trace_id": resolved_trace_id, "span_id": span.span_id},
                )
            )
            try:
                yield span
                await self.sink.write(
                    AuditEvent(
                        event="tool.call.end",
                        tenant_id=tenant_id,
                        tool_call_id=tool_call_id,
                        data={"trace_id": resolved_trace_id, "span_id": span.span_id},
                    )
                )
            except Exception as exc:
                await self.sink.write(
                    AuditEvent(
                        event="tool.call.error",
                        tenant_id=tenant_id,
                        tool_call_id=tool_call_id,
                        data={"error": str(exc), "trace_id": resolved_trace_id, "span_id": span.span_id},
                    )
                )
                raise
