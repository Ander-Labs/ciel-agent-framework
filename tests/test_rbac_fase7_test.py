"""Tests Fase 7 — RBACEngine + OIDCVerifier."""
from __future__ import annotations

import importlib

import pytest

from ciel.enterprise.rbac import (
    FeatureUnavailable,
    OIDCVerifier,
    RBACEngine,
    RBACError,
)


def _oidc_available() -> bool:
    try:
        importlib.import_module("jwt")
        return True
    except Exception:
        return False


def test_assign_and_has_permission_allow():
    eng = RBACEngine()
    eng.assign("alice", "operator")
    assert eng.has_permission("alice", "agent:run") is True
    eng.check("alice", "agent:run")  # no lanza


def test_role_without_permission_denies():
    eng = RBACEngine()
    eng.assign("bob", "viewer")
    assert eng.has_permission("bob", "agent:run") is False
    with pytest.raises(RBACError):
        eng.check("bob", "agent:run")


def test_wildcard_permission():
    eng = RBACEngine()
    eng.assign("carol", "admin")
    # admin tiene "agent:*" -> autoriza "agent:run"
    assert eng.has_permission("carol", "agent:run") is True
    assert eng.has_permission("carol", "tools:exec") is True


def test_tenant_isolation():
    eng = RBACEngine()
    eng.assign("dave", "operator", tenant_id="t1")
    # autorizado en t1
    assert eng.has_permission("dave", "agent:run", tenant_id="t1") is True
    # aislado de otro tenant t2 (sin asignación global)
    assert eng.has_permission("dave", "agent:run", tenant_id="t2") is False
    assert eng.role_of("dave", tenant_id="t2") is None


def test_list_roles():
    eng = RBACEngine()
    roles = eng.list_roles()
    assert "admin" in roles
    assert "operator" in roles
    assert "viewer" in roles


def test_snapshot_roundtrip():
    eng = RBACEngine()
    eng.assign("eve", "admin", tenant_id="t9")
    snap = eng.snapshot()
    eng2 = RBACEngine.from_snapshot(snap)
    assert eng2.has_permission("eve", "admin:*", tenant_id="t9") is True


def test_oidc_feature_detection():
    verifier = OIDCVerifier()
    if not _oidc_available():
        assert OIDCVerifier.OIDC_AVAILABLE is False
        with pytest.raises(FeatureUnavailable):
            verifier.verify("dummy.token.here")
    else:
        import jwt  # type: ignore

        assert OIDCVerifier.OIDC_AVAILABLE is True
        secret = "test-secret"
        token = jwt.encode(
            {"sub": "user1", "roles": ["operator"], "tenant_id": "t1"},
            secret,
            algorithm="HS256",
        )
        v = OIDCVerifier(public_key=secret)
        claims = v.verify(token)
        assert claims["sub"] == "user1"
        assert claims["tenant_id"] == "t1"
