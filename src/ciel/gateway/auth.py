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
