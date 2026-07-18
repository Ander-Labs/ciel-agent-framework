"""Optional transport-level API key authentication for gateway surfaces.

This module provides a FastAPI dependency that enforces an *optional* API key
on protected routes. The behaviour is driven by the ``CIEL_API_KEY``
environment variable (or an explicit key passed by the caller):

* When a key **is** configured, every protected route requires a valid key
  supplied via the ``Authorization: Bearer <key>`` header or the ``X-API-Key``
  header. A missing or mismatched key yields ``401 Unauthorized``.
* When **no** key is configured (the default for offline/dev/smoke-test
  deployments) the dependency is a no-op and the request proceeds. This keeps
  the gateway bootable with zero configuration.

The comparison uses :func:`hmac.compare_digest` to avoid timing side-channels.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException
from fastapi.params import Depends

__all__ = [
    "API_KEY_ENV",
    "read_expected_key",
    "make_auth_dependency",
    "require_api_key",
    "depends",
    "AuthContext",
    "make_oidc_dependency",
]


# Environment variable that, when set, enables transport auth.
API_KEY_ENV = "CIEL_API_KEY"


def read_expected_key(*, explicit: Optional[str] = None) -> Optional[str]:
    """Return the configured API key, preferring an explicit value.

    Parameters
    ----------
    explicit:
        A key passed directly by the caller. If provided (even when empty
        string), it takes precedence over the environment.
    """
    if explicit is not None:
        return explicit or None
    return os.getenv(API_KEY_ENV) or None


def _extract_provided_key(
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Optional[str]:
    """Pull the key out of the supported headers."""
    if authorization:
        value = authorization.strip()
        # Accept both "Bearer <key>" and a bare key.
        if value.lower().startswith("bearer "):
            return value[len("bearer ") :].strip() or None
        return value or None
    if x_api_key:
        return x_api_key.strip() or None
    return None


def _reject() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid or missing API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def make_auth_dependency(expected_key: Optional[str] = None):
    """Build a FastAPI dependency enforcing an optional API key.

    The returned callable reads ``expected_key`` (explicit) or falls back to
    the ``CIEL_API_KEY`` environment variable at request time. This lets the
    same closure be reused across requests while still honoring runtime env
    changes (e.g. ``monkeypatch.setenv`` in tests).
    """

    async def _guard(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> None:
        expected = read_expected_key(explicit=expected_key)
        if expected is None:
            # Open mode: no transport auth configured.
            return
        provided = _extract_provided_key(authorization, x_api_key)
        if provided is None or not hmac.compare_digest(provided, expected):
            raise _reject()

    return _guard


# Default dependency that always defers to the environment variable. This is
# the drop-in dependency for routes that should use whatever ``CIEL_API_KEY``
# is configured (if any).
require_api_key = make_auth_dependency(expected_key=None)


def depends(api_key: Optional[str] = None):
    """Helper returning a ``Depends(...)`` for a given key/configuration."""
    return Depends(make_auth_dependency(expected_key=api_key))


# ---------------------------------------------------------------------------
# OIDC (Fase 15): SSO/OIDC opt-in con fallback a api_key.
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class AuthContext:
    """Contexto de autenticación resuelto por la dependency.

    ``subject`` y ``role`` provienen de los claims OIDC cuando el token se validó
    contra un IdP real; en modo api_key/open ambos son ``None``.
    """

    subject: Optional[str] = None
    role: Optional[str] = None
    claims: Optional[dict] = None
    via: str = "open"  # "open" | "api_key" | "oidc"


def make_oidc_dependency(
    *,
    verifier=None,
    enabled: Optional[bool] = None,
    api_key: Optional[str] = None,
):
    """Build a FastAPI dependency that enforces OIDC when enabled.

    Behaviour:

    * When OIDC is **disabled** (``enabled`` is False, or None and
      ``CIEL_OIDC_ENABLED`` is unset), it fully delegates to the api_key guard
      (retrocompatibilidad total, open-mode por defecto).
    * When OIDC is **enabled**, every protected route requires a valid Bearer
      JWT. The token is verified (local key or JWKS) and its claims are mapped to
      an RBAC role. Missing/invalid token => ``401``.

    The dependency returns an :class:`AuthContext`.
    """
    from ciel.enterprise.rbac import FeatureUnavailable, OIDCVerifier

    def _is_enabled() -> bool:
        if enabled is not None:
            return enabled
        return OIDCVerifier.enabled_from_env()

    api_key_guard = make_auth_dependency(expected_key=api_key)

    async def _guard(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> AuthContext:
        if not _is_enabled():
            # Fallback: comportamiento api_key (open-mode si no hay clave).
            await api_key_guard(authorization=authorization, x_api_key=x_api_key)
            return AuthContext(via="open" if read_expected_key(explicit=api_key) is None else "api_key")

        token = _extract_provided_key(authorization, x_api_key)
        if token is None:
            raise _reject()
        active_verifier = verifier or OIDCVerifier.from_config()
        try:
            claims, role = active_verifier.verify_and_map_role(token)
        except FeatureUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # verificación fallida
            raise HTTPException(
                status_code=401,
                detail="Invalid OIDC token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        subject = claims.get("sub") if isinstance(claims, dict) else None
        return AuthContext(subject=subject, role=role, claims=claims, via="oidc")

    return _guard
