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
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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


@dataclass
class LeasedSecret:
    """A secret obtained from a dynamic backend with an associated lease.

    ``lease_id`` is ``None`` for static (KV) secrets — those never expire and
    take the plain static resolution path. Dynamic engines populate ``lease_id``,
    ``ttl`` and ``expires_at`` so the store can renew/revoke before expiry.
    """

    name: str
    value: str
    lease_id: Optional[str] = None
    ttl: Optional[float] = None
    expires_at: Optional[float] = None
    renewable: bool = False

    def is_expired(self, *, now: Optional[float] = None, skew: float = 0.0) -> bool:
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= (self.expires_at - skew)


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

    def get_lease(self, name: str, *, mount_point: Optional[str] = None) -> Optional[LeasedSecret]:
        """Read a *dynamic* secret from Vault, returning a :class:`LeasedSecret`.

        Uses Vault's generic ``read`` on the given path, which returns a
        ``lease_id``/``lease_duration``/``renewable`` envelope for dynamic
        secret engines (database, aws, ...). Falls back to a static
        :class:`LeasedSecret` (``lease_id=None``) when the path is a KV secret
        with no lease. Returns ``None`` when the secret cannot be resolved.
        """
        client = self._resolve_client()
        path = name if mount_point is None else f"{mount_point}/{name}"
        try:
            resp = client.read(path)
        except FeatureUnavailable:
            raise
        except Exception:
            return None
        if not resp:
            return None
        data = resp.get("data") or {}
        # dynamic engines expose the value under a well-known key or the whole map
        value = data.get(name)
        if value is None and len(data) == 1:
            value = next(iter(data.values()))
        if value is None:
            return None
        value = value if isinstance(value, str) else str(value)
        lease_id = resp.get("lease_id") or None
        ttl = resp.get("lease_duration")
        ttl = float(ttl) if ttl else None
        expires_at = (time.time() + ttl) if ttl else None
        return LeasedSecret(
            name=name,
            value=value,
            lease_id=lease_id,
            ttl=ttl,
            expires_at=expires_at,
            renewable=bool(resp.get("renewable", False)),
        )

    def revoke_lease(self, lease_id: str) -> None:
        """Best-effort revocation of a Vault lease (no-op if it fails)."""
        if not lease_id:
            return
        client = self._resolve_client()
        try:
            client.sys.revoke_lease(lease_id=lease_id)
        except Exception:
            pass


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


class RotatingSecretStore:
    """Resolve secrets that may expire, with lease-aware caching and rotation.

    Wraps a *dynamic* backend (must expose ``get_lease(name) -> LeasedSecret``,
    e.g. :class:`VaultSecretBackend`) and, optionally, a *static* fallback
    backend (anything with ``get(name) -> str | None``, e.g.
    :class:`EnvSecretBackend`).  Resolution rules:

    * A cached, non-expired :class:`LeasedSecret` is returned immediately.
    * On expiry (or first access) the dynamic backend is queried again; the old
      lease is revoked first (best-effort) to avoid lease leaks.
    * Static secrets (``lease_id is None``) are cached without a refresh timer.
    * On any dynamic-backend failure the store degrades to the last-known-good
      cached value, and then to the static fallback backend — never raising for
      transient network errors (offline-safe).

    ``resolve`` is call-time safe (thread-locked); consumers should call it on
    every use instead of caching the string, so rotation actually takes effect.
    """

    def __init__(
        self,
        dynamic_backend,
        *,
        fallback_backend=None,
        refresh_ratio: float = 0.75,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._dynamic = dynamic_backend
        self._fallback = fallback_backend
        self._refresh_ratio = refresh_ratio
        self._clock = clock
        self._cache: dict[str, LeasedSecret] = {}
        self._lock = threading.RLock()

    def _needs_refresh(self, leased: LeasedSecret) -> bool:
        if leased.lease_id is None or leased.expires_at is None or leased.ttl is None:
            return False  # static secret: never auto-refresh
        # refresh proactively once refresh_ratio of the TTL has elapsed
        threshold = leased.expires_at - leased.ttl * (1.0 - self._refresh_ratio)
        return self._clock() >= threshold

    def resolve(self, name: str) -> Optional[str]:
        with self._lock:
            cached = self._cache.get(name)
            if cached is not None and not self._needs_refresh(cached):
                return cached.value

            # Try to (re)fetch from the dynamic backend.
            try:
                fresh = self._dynamic.get_lease(name)
            except FeatureUnavailable:
                raise
            except Exception:
                fresh = None

            if fresh is not None:
                # revoke the previous lease before swapping (avoid lease leaks)
                if cached is not None and cached.lease_id and cached.lease_id != fresh.lease_id:
                    self._revoke(cached.lease_id)
                self._cache[name] = fresh
                return fresh.value

            # Dynamic backend failed → last-known-good, then static fallback.
            if cached is not None:
                return cached.value
            if self._fallback is not None:
                return self._fallback.get(name)
            return None

    def require(self, name: str) -> str:
        value = self.resolve(name)
        if value is None:
            raise SecretError(f"required secret not found: {name}")
        return value

    def invalidate(self, name: str) -> None:
        """Drop the cached value so the next ``resolve`` re-fetches."""
        with self._lock:
            self._cache.pop(name, None)

    def revoke(self, name: str) -> None:
        """Revoke and drop the lease for *name* (dynamic secrets only)."""
        with self._lock:
            cached = self._cache.pop(name, None)
        if cached is not None and cached.lease_id:
            self._revoke(cached.lease_id)

    def _revoke(self, lease_id: str) -> None:
        revoke = getattr(self._dynamic, "revoke_lease", None)
        if callable(revoke):
            try:
                revoke(lease_id)
            except Exception:
                pass
