"""Tests offline para F-OIDC (Fase 15 — SSO/OIDC con proveedor real).

Todos los tests corren SIN red: firmamos JWTs sintéticos con una clave RSA
generada en memoria y validamos con ``public_key`` local o con un JWKS falso
inyectado. Los tests que requieren un IdP real se marcan ``skip``.
"""
from __future__ import annotations

import os
import time

import pytest

jwt = pytest.importorskip("jwt")
crypto = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ciel.enterprise.rbac import (
    FeatureUnavailable,
    OIDCVerifier,
    map_oidc_claims_to_role,
)


ISSUER = "https://idp.example.com/realms/ciel"
AUDIENCE = "ciel-api"


@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _make_token(priv_pem, *, iss=ISSUER, aud=AUDIENCE, exp_delta=3600, alg="RS256", extra=None, kid=None):
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_delta,
    }
    if extra:
        payload.update(extra)
    headers = {"kid": kid} if kid else None
    return jwt.encode(payload, priv_pem, algorithm=alg, headers=headers)


# --------------------------------------------------------------------------
# Verificación local (retrocompat Fase 7)
# --------------------------------------------------------------------------

def test_oidc_verifier_offline_local_key(rsa_keypair):
    priv, pub = rsa_keypair
    token = _make_token(priv, extra={"roles": ["operator"]})
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    claims = v.verify(token)
    assert claims["sub"] == "user-123"


def test_oidc_verifier_rejects_wrong_iss(rsa_keypair):
    priv, pub = rsa_keypair
    token = _make_token(priv, iss="https://evil.example.com")
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    with pytest.raises(Exception):
        v.verify(token)


def test_oidc_verifier_rejects_wrong_aud(rsa_keypair):
    priv, pub = rsa_keypair
    token = _make_token(priv, aud="other-api")
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    with pytest.raises(Exception):
        v.verify(token)


def test_oidc_verifier_rejects_expired(rsa_keypair):
    priv, pub = rsa_keypair
    token = _make_token(priv, exp_delta=-10)
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    with pytest.raises(Exception):
        v.verify(token)


def test_oidc_verifier_rejects_alg_none(rsa_keypair):
    _, pub = rsa_keypair
    # Token firmado con alg=none (sin firma) debe ser rechazado.
    token = jwt.encode({"sub": "x", "iss": ISSUER, "aud": AUDIENCE}, None, algorithm="none")
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    with pytest.raises(Exception):
        v.verify(token)


# --------------------------------------------------------------------------
# Mapeo de claims → rol
# --------------------------------------------------------------------------

def test_map_oidc_claims_to_role_keycloak():
    claims = {"realm_access": {"roles": ["ciel-admin", "offline_access"]}}
    assert map_oidc_claims_to_role(claims) == "admin"


def test_map_oidc_claims_to_role_auth0():
    claims = {"roles": ["operator"]}
    assert map_oidc_claims_to_role(claims) == "operator"


def test_map_oidc_claims_to_role_azure_groups():
    claims = {"groups": ["viewer"]}
    assert map_oidc_claims_to_role(claims) == "viewer"


def test_map_oidc_claims_to_role_custom_mapping():
    claims = {"roles": ["superuser"]}
    assert map_oidc_claims_to_role(claims, role_mapping={"superuser": "admin"}) == "admin"


def test_map_oidc_claims_to_role_no_match_returns_none():
    claims = {"roles": ["unknown-group"]}
    assert map_oidc_claims_to_role(claims) is None


def test_verify_and_map_role(rsa_keypair):
    priv, pub = rsa_keypair
    token = _make_token(priv, extra={"realm_access": {"roles": ["operator"]}})
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    claims, role = v.verify_and_map_role(token)
    assert claims["sub"] == "user-123"
    assert role == "operator"


# --------------------------------------------------------------------------
# from_config / env
# --------------------------------------------------------------------------

def test_from_config_reads_env(monkeypatch):
    monkeypatch.setenv("CIEL_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("CIEL_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("CIEL_OIDC_ROLE_MAPPING", "boss:admin,peon:viewer")
    v = OIDCVerifier.from_config()
    assert v.issuer == ISSUER
    assert v.audience == AUDIENCE
    assert v.role_mapping == {"boss": "admin", "peon": "viewer"}


def test_enabled_from_env(monkeypatch):
    monkeypatch.delenv("CIEL_OIDC_ENABLED", raising=False)
    assert OIDCVerifier.enabled_from_env() is False
    monkeypatch.setenv("CIEL_OIDC_ENABLED", "true")
    assert OIDCVerifier.enabled_from_env() is True


# --------------------------------------------------------------------------
# JWKS con fake client (sin red)
# --------------------------------------------------------------------------

def test_oidc_verifier_jwks_with_fake_signing_key(rsa_keypair, monkeypatch):
    priv, pub = rsa_keypair
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pub_key_obj = load_pem_public_key(pub)
    token = _make_token(priv, kid="key-1", extra={"roles": ["admin"]})

    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_uri="https://idp/jwks")

    def _fake_refresh():
        v._jwks_cache = {"key-1": pub_key_obj}
        v._jwks_fetched_at = time.time()

    monkeypatch.setattr(v, "_refresh_jwks", _fake_refresh)
    claims, role = v.verify_and_map_role(token)
    assert claims["sub"] == "user-123"
    assert role == "admin"


def test_oidc_verifier_jwks_unknown_kid_raises(rsa_keypair, monkeypatch):
    priv, pub = rsa_keypair
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pub_key_obj = load_pem_public_key(pub)
    token = _make_token(priv, kid="key-2")
    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_uri="https://idp/jwks")

    def _fake_refresh():
        v._jwks_cache = {"key-1": pub_key_obj}
        v._jwks_fetched_at = time.time()

    monkeypatch.setattr(v, "_refresh_jwks", _fake_refresh)
    with pytest.raises(FeatureUnavailable):
        v.verify(token)


# --------------------------------------------------------------------------
# Gateway dependency: fallback y enforcement
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oidc_dependency_falls_back_to_api_key_when_disabled(monkeypatch):
    from ciel.gateway.auth import make_oidc_dependency

    monkeypatch.delenv("CIEL_API_KEY", raising=False)
    guard = make_oidc_dependency(enabled=False)
    ctx = await guard(authorization=None, x_api_key=None)
    assert ctx.via == "open"


@pytest.mark.asyncio
async def test_oidc_dependency_requires_token_when_enabled(rsa_keypair):
    from fastapi import HTTPException

    from ciel.gateway.auth import make_oidc_dependency

    priv, pub = rsa_keypair
    verifier = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    guard = make_oidc_dependency(enabled=True, verifier=verifier)

    # Sin token → 401
    with pytest.raises(HTTPException) as ei:
        await guard(authorization=None, x_api_key=None)
    assert ei.value.status_code == 401

    # Token válido → AuthContext con rol
    token = _make_token(priv, extra={"roles": ["operator"]})
    ctx = await guard(authorization=f"Bearer {token}", x_api_key=None)
    assert ctx.via == "oidc"
    assert ctx.subject == "user-123"
    assert ctx.role == "operator"


@pytest.mark.asyncio
async def test_oidc_dependency_rejects_invalid_token_when_enabled(rsa_keypair):
    from fastapi import HTTPException

    from ciel.gateway.auth import make_oidc_dependency

    _, pub = rsa_keypair
    verifier = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE, public_key=pub)
    guard = make_oidc_dependency(enabled=True, verifier=verifier)
    with pytest.raises(HTTPException) as ei:
        await guard(authorization="Bearer not-a-jwt", x_api_key=None)
    assert ei.value.status_code == 401


# --------------------------------------------------------------------------
# Tests que requieren un IdP real (skip por defecto)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not os.getenv("CIEL_OIDC_ISSUER_LIVE"), reason="requiere IdP real")
def test_oidc_discovery_jwks_live():
    v = OIDCVerifier(issuer=os.environ["CIEL_OIDC_ISSUER_LIVE"], audience=os.getenv("CIEL_OIDC_AUDIENCE"))
    uri = v._discover_jwks_uri()
    assert uri.startswith("http")
