from __future__ import annotations

import pytest

from ciel.observability import (
    AuditEvent,
    AuditSink,
    InMemoryAuditSink,
    NullAuditSink,
    propagate,
    TraceSpan,
    assert_tenant_event,
)


@pytest.mark.asyncio
async def test_in_memory_audit_sink_appends_event() -> None:
    sink = InMemoryAuditSink()
    event = AuditEvent(event="start", tenant_id="t1")
    await sink.write(event)
    assert len(sink.events) == 1
    assert sink.events[0].tenant_id == "t1"


@pytest.mark.asyncio
async def test_null_audit_sink_swallows_event() -> None:
    sink = NullAuditSink()
    await sink.write(AuditEvent(event="heartbeat"))
    assert isinstance(sink, AuditSink)


def test_propagate_uses_explicit_tenant_id() -> None:
    event = AuditEvent(event="run")
    result = propagate(event, tenant_id="tenant-7")
    assert result.tenant_id == "tenant-7"
    assert event is result


def test_propagate_reuses_event_tenant_id_when_missing() -> None:
    event = AuditEvent(event="run", tenant_id="tenant-9")
    result = propagate(event)
    assert result.tenant_id == "tenant-9"


def test_propagate_raises_when_tenant_id_missing() -> None:
    event = AuditEvent(event="run")
    with pytest.raises(ValueError):
        propagate(event)


def test_assert_tenant_event_raises_for_none() -> None:
    with pytest.raises(ValueError):
        assert_tenant_event(AuditEvent(event="run"))


def test_assert_tenant_event_accepts_valid_tenant() -> None:
    assert_tenant_event(AuditEvent(event="run", tenant_id="t1"))


@pytest.mark.asyncio
async def test_trace_span_add_event_propagates_tenant() -> None:
    span = TraceSpan(trace_id="trace-1", span_id="span-1")
    event = span.add_event(AuditEvent(event="step"), tenant_id="tenant-x")
    assert event.tenant_id == "tenant-x"
    assert event.data["trace_id"] == "trace-1"
    assert event.data["span_id"] == "span-1"
    assert len(span.events) == 1


@pytest.mark.asyncio
async def test_trace_span_start_child() -> None:
    parent = TraceSpan(trace_id="trace-1", span_id="span-1", tenant_id="tenant-x")
    async with parent.start_child("child", tenant_id="tenant-x") as child:
        assert child.parent_span_id == "span-1"
        assert child.tenant_id == "tenant-x"
        assert child.name == "child"
        assert child.trace_id == "trace-1"
