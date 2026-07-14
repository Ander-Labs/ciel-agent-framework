from __future__ import annotations

import pytest

from ciel.security import (
    ApprovalDecision,
    PIIScrubber,
    TenantIsolationPolicy,
    ApprovalRequest,
)


def test_tenant_isolation_policy_approves_when_tenant_is_set() -> None:
    policy = TenantIsolationPolicy()
    request = ApprovalRequest(
        request_id="r-1",
        actor="user-1",
        tool="filesystem",
        arguments={},
        risk="medium",
        tenant="acme",
    )
    decision = policy.evaluate(request)
    assert decision.approved is True
    assert decision.tenant == "acme"


def test_tenant_isolation_policy_rejects_missing_tenant() -> None:
    policy = TenantIsolationPolicy()
    request = ApprovalRequest(
        request_id="r-2",
        actor="user-1",
        tool="filesystem",
        arguments={},
        risk="medium",
    )
    decision = policy.evaluate(request)
    assert decision.approved is False


def test_validate_decision_tenant_mismatch() -> None:
    request = ApprovalRequest(
        request_id="r-1",
        actor="user-1",
        tool="filesystem",
        arguments={},
        risk="medium",
        tenant="acme",
    )
    decision = ApprovalDecision(
        request_id="r-1",
        approved=True,
        tenant="other",
    )
    assert TenantIsolationPolicy.validate_decision_tenant(request, decision) is False


def test_pii_scrubber_redacts_email_phone_and_dni() -> None:
    clean = PIIScrubber.scrub("Contact me at juan@example.com or +34 600 123 456. DNI 12345678A.")
    assert "@example.com" not in clean
    assert "600 123 456" not in clean
    assert "12345678A" not in clean


def test_pii_scrubber_safe_text_redacts_secrets_and_pii() -> None:
    clean = PIIScrubber.safe_text("User us3r with api_key=ABCDEFGHIJKL and juan@example.com")
    assert "ABCDEFGHIJKL" not in clean
    assert "@example.com" not in clean
