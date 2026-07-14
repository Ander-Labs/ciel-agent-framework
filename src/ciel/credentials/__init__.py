from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
)

from ciel.common import CielError


T = TypeVar("T")


class CredentialPoolError(CielError):
    """Base error for credential pool operations."""


class CredentialPoolExhausted(CredentialPoolError):
    """Raised when all credentials for a provider are exhausted."""


@dataclass(frozen=True)
class ProviderCredentials:
    """Credentials for a specific provider."""

    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    tenant: Optional[str] = None
    default_model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnvCredentialManager:
    """Loads credentials from environment variables.

    Convention by provider name:
      CIEL_<PROVIDER>_API_KEY
      CIEL_<PROVIDER>_BASE_URL
      CIEL_<PROVIDER>_TENANT
      CIEL_<PROVIDER>_DEFAULT_MODEL
    """

    _prefix = "CIEL"

    def load(self, provider: str) -> ProviderCredentials:
        prefix = f"{self._prefix}_{provider.upper()}"
        api_key = os.getenv(f"{prefix}_API_KEY")
        base_url = os.getenv(f"{prefix}_BASE_URL")
        tenant = os.getenv(f"{prefix}_TENANT")
        default_model = os.getenv(f"{prefix}_DEFAULT_MODEL")
        metadata: Dict[str, Any] = {}
        for key, value in os.environ.items():
            if key.startswith(f"{prefix}_"):
                suffix = key[len(prefix) + 1 :]
                if suffix not in {
                    "API_KEY",
                    "BASE_URL",
                    "TENANT",
                    "DEFAULT_MODEL",
                }:
                    metadata[suffix.lower()] = value

        return ProviderCredentials(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            tenant=tenant,
            default_model=default_model,
            metadata=metadata,
        )


@dataclass
class CredentialRecord:
    """A single credential entry with optional lifecycle state."""

    value: ProviderCredentials
    exhausted: bool = False
    exhausted_reason: Optional[str] = None

    def mark_exhausted(self, reason: Optional[str] = None) -> None:
        self.exhausted = True
        self.exhausted_reason = reason


class ProviderCredentialPool:
    """Pool of credentials for a specific provider.

    Supports simple round-robin rotation, skip exhausted entries,
    and reset of exhausted state.
    """

    def __init__(
        self,
        provider: str,
        credentials: Sequence[ProviderCredentials],
        *,
        allow_rotation: bool = True,
        on_exhausted: str = "skip",
    ) -> None:
        if not credentials:
            raise CredentialPoolError(f"No credentials provided for provider: {provider}")
        if on_exhausted not in {"skip", "error"}:
            raise CredentialPoolError(f"Unsupported on_exhausted policy: {on_exhausted}")

        self._provider = provider
        self._records: List[CredentialRecord] = [
            CredentialRecord(value=c) for c in credentials
        ]
        self._allow_rotation = allow_rotation
        self._on_exhausted = on_exhausted
        self._index = 0

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def total(self) -> int:
        return len(self._records)

    @property
    def available(self) -> int:
        return sum(1 for record in self._records if not record.exhausted)

    def next(self) -> ProviderCredentials:
        """Return the next available credential.

        Raises:
            CredentialPoolExhausted: If all credentials are exhausted and the
                policy is `error`, or if there are no available credentials.
        """
        if not self._allow_rotation:
            active = next(
                (record for record in self._records if not record.exhausted), None
            )
            if active is None:
                self._raise_if_error_or_skip_empty()
                raise CredentialPoolExhausted(
                    f"Credential pool exhausted for provider: {self._provider}"
                )
            return active.value

        length = self.total
        for _ in range(length):
            record = self._records[self._index]
            self._index = (self._index + 1) % length
            if not record.exhausted:
                return record.value

        self._raise_if_error_or_skip_empty()
        raise CredentialPoolExhausted(
            f"Credential pool exhausted for provider: {self._provider}"
        )

    def mark_exhausted(self, credential: ProviderCredentials, reason: Optional[str] = None) -> None:
        """Mark a specific credential as exhausted.

        Uses provider + api_key + base_url to identify the record.
        """
        for record in self._records:
            if self._match(record.value, credential):
                record.mark_exhausted(reason)
                return

    def reset(self, credential: ProviderCredentials) -> None:
        """Clear exhausted state for the provided credential."""
        for record in self._records:
            if self._match(record.value, credential):
                record.exhausted = False
                record.exhausted_reason = None
                return

    def reset_all(self) -> None:
        """Reset exhausted state for all credentials."""
        for record in self._records:
            record.exhausted = False
            record.exhausted_reason = None

    def iter_records(self) -> Iterator[CredentialRecord]:
        return iter(self._records)

    def _match(self, a: ProviderCredentials, b: ProviderCredentials) -> bool:
        return all(
            getattr(a, attr) == getattr(b, attr)
            for attr in ("provider", "api_key", "base_url", "tenant", "default_model")
        )

    def _raise_if_error_or_skip_empty(self) -> None:
        if self.available == 0 and self._on_exhausted == "error":
            raise CredentialPoolExhausted(
                f"Credential pool exhausted for provider: {self._provider}"
            )


class CredentialPools:
    """Registry of provider credential pools."""

    def __init__(self) -> None:
        self._pools: Dict[str, ProviderCredentialPool] = {}

    def register(self, pool: ProviderCredentialPool) -> None:
        self._pools[pool.provider] = pool

    def pool(self, provider: str) -> ProviderCredentialPool:
        if provider not in self._pools:
            raise CredentialPoolError(f"No credential pool registered for provider: {provider}")
        return self._pools[provider]

    def providers(self) -> Sequence[str]:
        return list(self._pools.keys())

    def next(self, provider: str) -> ProviderCredentials:
        return self.pool(provider).next()


def load_pools_from_env(
    providers: Sequence[str],
    *,
    manager: Optional[EnvCredentialManager] = None,
    allow_rotation: bool = True,
    on_exhausted: str = "skip",
) -> CredentialPools:
    """Build a `CredentialPools` registry from environment credentials.

    Loads the base credential from the unified env var scheme. If an
    additional environment variable `CIEL_<PROVIDER>_POOL` exists, it
    is treated as a newline-separated list of JSON-encoded `ProviderCredentials`
    that are appended to the pool.
    """
    manager = manager or EnvCredentialManager()
    pools = CredentialPools()

    for provider in providers:
        base = manager.load(provider)
        credentials: List[ProviderCredentials] = []
        if base.api_key or base.base_url:
            credentials.append(base)

        pool_key = f"CIEL_{provider.upper()}_POOL"
        raw = os.getenv(pool_key)
        if raw:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload: Dict[str, Any] = __import__("json").loads(line)
                except Exception as exc:
                    raise CredentialPoolError(
                        f"Invalid JSON in {pool_key}: {exc}"
                    ) from exc
                credentials.append(
                    ProviderCredentials(
                        provider=provider,
                        api_key=payload.get("api_key"),
                        base_url=payload.get("base_url"),
                        tenant=payload.get("tenant") or base.tenant,
                        default_model=payload.get("default_model") or base.default_model,
                        metadata={**base.metadata, **payload.get("metadata", {})},
                    )
                )

        if not credentials:
            credentials.append(base)

        pool = ProviderCredentialPool(
            provider,
            credentials,
            allow_rotation=allow_rotation,
            on_exhausted=on_exhausted,
        )
        pools.register(pool)

    return pools
