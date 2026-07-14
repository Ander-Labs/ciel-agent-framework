from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ciel.security.redaction import PIIScrubber
from ciel.security.redaction import redact_string as redact_secrets, redact_string, _PII_PATTERNS, _SECRET_PATTERNS, _scrub_pii
from ciel.security.approvals import ApprovalPolicy, ApprovalRequest, ApprovalDecision, SmartApprovalPolicy, YoloApprovalPolicy, TenantIsolationPolicy, from_name


@dataclass
class ApprovalRequest:
    request_id: str
    actor: str
    tool: str
    arguments: Dict[str, Any]
    risk: str
    justification: Optional[str] = None
    tenant: Optional[str] = None


@dataclass
class ApprovalDecision:
    request_id: str
    approved: bool
    approver: Optional[str] = None
    note: Optional[str] = None
    tenant: Optional[str] = None


class ApprovalPolicy:
    mode = "manual"

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        raise NotImplementedError


class ManualApprovalPolicy(ApprovalPolicy):
    mode = "manual"

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            request_id=request.request_id,
            approved=False,
            note="manual approval required",
            tenant=request.tenant,
        )


class TenantIsolationPolicy(ApprovalPolicy):
    mode = "tenant_isolation"

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        if not request.tenant:
            return ApprovalDecision(
                request_id=request.request_id,
                approved=False,
                note="missing tenant for isolation policy",
                tenant=request.tenant,
            )
        return ApprovalDecision(
            request_id=request.request_id,
            approved=True,
            note="tenant validated",
            tenant=request.tenant,
        )

    @staticmethod
    def validate_decision_tenant(request: ApprovalRequest, decision: ApprovalDecision) -> bool:
        if not request.tenant or not decision.tenant:
            return False
        return request.tenant == decision.tenant


__all__ = [
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalDecision",
    "SmartApprovalPolicy",
    "YoloApprovalPolicy",
    "TenantIsolationPolicy",
    "ManualApprovalPolicy",
    "from_name",
    "PIIScrubber",
    "redact",
    "redact_string",
    "redact_secrets",
]
