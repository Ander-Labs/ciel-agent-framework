"""Secret management for the Ciel enterprise layer.

Offers a small, pluggable :class:`SecretStore` backed by environment
variables, Kubernetes mounted files and HashiCorp Vault.  The module is
**offline-safe**: importing it never requires any optional dependency.  Vault
support is detected at import time; when ``hvac`` is missing the backend still
imports but :meth:`VaultSecretBackend.get` raises ``FeatureUnavailable``.

Backend priority convention (set explicitly by the caller through the
``backends`` list order): Vault > Kubernetes > env.  The store simply tries each
backend in the given order and returns the first non-``None`` value.

No secret is ever hard-coded here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - exercised through import machinery
    import hvac  # type: ignore

    VAULT_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    hvac = None  # type: ignore
    VAULT_AVAILABLE = False


class SecretError(Exception):
    """Raised when a required secret cannot be resolved."""


class FeatureUnavailable(Exception):
    """Raised when an optional backend's dependency is missing."""


def _k8s_filename(name: str) -> str:
    """Map a secret *name* to the file name Kubernetes mounts.

    Kubernetes lower-cases the key and converts underscores to dashes, so
    ``MY_SECRET_NAME`` becomes ``my-secret-name``.
    """
    return name.lower().replace("_", "-")


class EnvSecretBackend:
    """Resolve secrets from process environment variables.

    Always available and therefore the safest default backend.
    """

    def get(self, name: str) -> Optional[str]:
        return os.getenv(name)


class KubernetesSecretBackend:
    """Resolve secrets from files mounted by the Kubernetes secret store.

    Kubernetes mounts each key as a file inside ``mount_dir``; the file name is
    the key lower-cased with underscores replaced by dashes.  This backend is
    purely filesystem based and never touches the network.
    """

    def __init__(self, mount_dir: str | Path) -> None:
        self.mount_dir = Path(mount_dir)

    def get(self, name: str) -> Optional[str]:
        path = self.mount_dir / _k8s_filename(name)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")


class VaultSecretBackend:
    """Resolve secrets from HashiCorp Vault (KV v2) via ``hvac``.

    Requires the optional ``hvac`` dependency.  When ``hvac`` is unavailable
    :attr:`VAULT_AVAILABLE` is ``False`` and :meth:`get` raises
    :class:`FeatureUnavailable` instead of failing at import time.

    The client is created in memory; for tests a fake client can be injected via
    ``client=`` so no real network call is ever made.
    """

    VAULT_AVAILABLE: bool = VAULT_AVAILABLE

    def __init__(
        self,
        *,
        url: str,
        token: str,
        path_prefix: str = "/secret/data",
        client=None,
    ) -> None:
        self.url = url
        self.token = token
        self.path_prefix = path_prefix.rstrip("/")
        self._client = client

    def _resolve_client(self):
        if self._client is not None:
            return self._client
        if not VAULT_AVAILABLE:
            raise FeatureUnavailable(
                "Vault backend unavailable: the 'hvac' package is not installed"
            )
        return hvac.Client(url=self.url, token=self.token)

    def _path_for(self, name: str) -> str:
        return f"{self.path_prefix}/{name}"

    def get(self, name: str) -> Optional[str]:
        client = self._resolve_client()
        path = self._path_for(name)
        try:
            resp = client.secrets.kv.v2.read_secret_version(path=path, raise_on_deleted_version=False)
        except FeatureUnavailable:
            raise
        except Exception:
            # Any transport / not-found error degrades to "no secret".
            return None
        try:
            data = resp["data"]["data"]
        except (KeyError, TypeError):
            return None
        value = data.get(name)
        return value if isinstance(value, str) else (None if value is None else str(value))


class SecretStore:
    """Aggregate several backends and resolve by priority order.

    ``get`` tries each backend in the supplied order and returns the first
    non-``None`` value.  ``require`` is the strict variant that raises
    :class:`SecretError` when no backend can resolve the name.
    """

    def __init__(self, backends: list) -> None:
        if not backends:
            raise SecretError("SecretStore requires at least one backend")
        self.backends = list(backends)

    def get(self, name: str) -> Optional[str]:
        for backend in self.backends:
            value = backend.get(name)
            if value is not None:
                return value
        return None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise SecretError(f"required secret not found: {name}")
        return value
