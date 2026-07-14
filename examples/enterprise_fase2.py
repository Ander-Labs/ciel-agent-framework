"""Ejemplo enterprise Fase 2: approvals + redaction + observability + tenant.

Ejecutar:
    uv run python examples/enterprise_fase2.py
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cielo.common import CielError  # noqa,保持一致 proyecto
from cielo.security import PIIScrubber, ApprovalPolicy, ApprovalRequest, ApprovalDecision
from cielo.observability import AuditEvent, InMemoryAuditSink, TraceSpan
from cielo.providers import ChatProvider, ChatResponse, ChatChoice, ChatMessage
from cielo.runtime import ToolResult


class EchoProvider(ChatProvider):
    async def complete(self, request: Any) -> ChatResponse:
        return ChatResponse(choice=ChatChoice(message=ChatMessage(role="assistant", content="ok")))


class ManualApprover(ApprovalPolicy):
    mode = "manual"

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        allowed = {"list_dir", "read_doc"}
        approved = request.tool in allowed
        return ApprovalDecision(
            request_id=request.request_id,
            approved=approved,
            approver="manual-policy",
            note="allowed" if approved else "blocked by manual policy",
            tenant=request.tenant,
        )


@dataclass
class FakeTool:
    name: str
    raw: str


async def main() -> None:
    tenant_id = "tenant-acme"
    session_id = "s-fase2-demo"
    sink = InMemoryAuditSink()
    root = TraceSpan(trace_id="trace-1", span_id="span-1", tenant_id=tenant_id)
    await sink.write(AuditEvent(event="session.start", session_id=session_id, tenant_id=tenant_id))

    raw_payload = 'User admin@acme.com called tool payment:capture api_key=ABCDEFGHIJKL'
    redacted = PIIScrubber.safe_text(raw_payload)
    print(f"[REDACTED] {redacted}")

    async with root.start_child("approvals", tenant_id=tenant_id) as span:
        request = ApprovalRequest(request_id="r-1", actor="admin", tool="payment:capture", arguments={}, risk="low", tenant=tenant_id)
        policy: ApprovalPolicy = ManualApprover()
        decision: ApprovalDecision = policy.evaluate(request)
        span.add_event(AuditEvent(event="approval.evaluated", session_id=session_id, data={"approved": decision.approved}, tenant_id=tenant_id), tenant_id=tenant_id)
        print(f"[APPROVAL] approved={decision.approved} note={decision.note}")

    await sink.write(AuditEvent(event="session.end", session_id=session_id, tenant_id=tenant_id))
    print(f"[AUDIT] event_count={len(sink.events)}")
    print("[OK] enterprise_fase2 demo complete")


if __name__ == "__main__":
    asyncio.run(main())
