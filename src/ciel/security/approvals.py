from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ciel.security.redaction import PIIScrubber, redact_string as redact_secrets


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


class SmartApprovalPolicy(ApprovalPolicy):
    mode = "smart"
    _safe_tools = {"echo", "read_doc", "list_dir"}
    _medium_risk = {"write_note", "summarize"}
    _high_risk = {"delete_file", "payment:capture", "deploy"}

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        tool = request.tool
        risk = request.risk or "medium"
        if tool in self._safe_tools or risk == "low":
            return ApprovalDecision(
                request_id=request.request_id,
                approved=True,
                approver="smart-policy",
                note="auto-approved",
                tenant=request.tenant,
            )
        if tool in self._high_risk or risk == "high":
            return ApprovalDecision(
                request_id=request.request_id,
                approved=False,
                approver="smart-policy",
                note="blocked due to high risk",
                tenant=request.tenant,
            )
        return ApprovalDecision(
            request_id=request.request_id,
            approved=False,
            approver="smart-policy",
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


class YoloApprovalPolicy(ApprovalPolicy):
    mode = "yolo"

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            request_id=request.request_id,
            approved=True,
            approver="auto-yolo",
            note="auto-approved by yolo policy",
            tenant=request.tenant,
        )


def from_name(name: str) -> ApprovalPolicy:
    """Return an :class:`ApprovalPolicy` instance for a policy name.

    Supported names: ``manual``, ``smart``, ``yolo``, ``tenant_isolation``.
    Raises ``ValueError`` for unknown policy names so misconfiguration fails
    loudly instead of silently defaulting.
    """
    registry: Dict[str, type] = {
        "manual": ManualApprovalPolicy,
        "smart": SmartApprovalPolicy,
        "yolo": YoloApprovalPolicy,
        "tenant_isolation": TenantIsolationPolicy,
    }
    key = (name or "manual").lower()
    policy_cls = registry.get(key)
    if policy_cls is None:
        raise ValueError(
            f"Unknown approval policy: {name!r} (expected one of {sorted(registry)})"
        )
    return policy_cls()


__all__ = [
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalDecision",
    "SmartApprovalPolicy",
    "TenantIsolationPolicy",
    "YoloApprovalPolicy",
    "from_name",
]
