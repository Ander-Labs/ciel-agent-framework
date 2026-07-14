"""Central Ciel configuration module (ciel.yaml + env).

Generalizes the loader previously living in
``deploy/example-enterprise/config.py`` into a reusable package module. It
unifies in a single manifesto:

* :class:`CielConfig` dataclass -- default tenant, approval policy, providers,
  tenants, audit and gateway settings;
* :func:`load` -- read a ``ciel.yaml`` manifesto and resolve secrets from the
  environment (API keys are referenced by ``api_key_env``, never plaintext);
* :func:`build_runtime` -- wire a :class:`ciel.runtime.DefaultAgentRuntime`
  from a :class:`CielConfig`;
* :func:`build_app` -- compose the full gateway FastAPI app via
  :func:`ciel.gateway.server.make_app` using the resolved default tenant.

Multi-tenancy is never relaxed: every runtime/tool request still requires a
``tenant_id`` and ``build_runtime`` is lenient only in the absence of
configured providers (it falls back to an offline echo provider so the
runtime stays bootable for smoke tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ciel.security.approvals import from_name as _approval_from_name
from ciel.providers import OpenAICompatibleProvider, ProviderConfig, ProviderFactory, ProviderRegistry
from ciel.runtime import (
    ChatProvider,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolRegistry,
)


@dataclass
class ProviderEntry:
    """A single provider entry from the ciel.yaml ``providers`` list."""

    name: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    timeout: float = 30.0
    tenant: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderEntry":
        api_key_env = data.get("api_key_env")
        api_key = data.get("api_key")
        if api_key is None and api_key_env:
            api_key = os.getenv(api_key_env)
        return cls(
            name=data["name"],
            base_url=data.get("base_url"),
            api_key_env=api_key_env,
            api_key=api_key,
            default_model=data.get("default_model"),
            timeout=float(data.get("timeout", 30.0)),
            tenant=data.get("tenant"),
        )

    def to_provider_config(self) -> ProviderConfig:
        return ProviderConfig(
            name=self.name,
            base_url=self.base_url or "",
            api_key=self.api_key,
            default_model=self.default_model,
            timeout=self.timeout,
            tenant=self.tenant,
        )


@dataclass
class AuditConfig:
    """Audit sink configuration.

    ``driver`` is one of ``jsonl`` or ``otel`` (``null``/``none`` disables
    durable auditing and uses the in-memory sink). For ``jsonl`` an optional
    ``path`` selects the output directory.
    """

    driver: str = "null"
    path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AuditConfig":
        if not data:
            return cls(driver="null")
        return cls(driver=data.get("driver", "null"), path=data.get("path"))


@dataclass
class GatewayConfig:
    """Gateway binding configuration (host/port/bind)."""

    host: str = "0.0.0.0"
    port: int = 8080
    bind: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "GatewayConfig":
        if not data:
            return cls()
        return cls(
            host=data.get("host", "0.0.0.0"),
            port=int(data.get("port", 8080)),
            bind=data.get("bind"),
        )


@dataclass
class CielConfig:
    """Central Ciel deploy manifesto (parsed from ciel.yaml + env)."""

    default_tenant: Optional[str] = None
    approval_policy: str = "manual"
    providers: List[ProviderEntry] = field(default_factory=list)
    tenants: List[str] = field(default_factory=list)
    audit: AuditConfig = field(default_factory=AuditConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)

    @property
    def provider_registry(self) -> ProviderRegistry:
        """Build a :class:`ProviderRegistry` from the configured providers.

        Providers with a resolvable ``base_url`` are instantiated through
        :class:`ProviderFactory`; providers missing a ``base_url`` are skipped
        (so env-only/offline manifests stay bootable).
        """
        registry = ProviderRegistry()
        for entry in self.providers:
            if not entry.base_url:
                continue
            provider = ProviderFactory.from_config(entry.to_provider_config())
            registry.register(entry.name, provider, config={"tenant": entry.tenant})
        return registry

    def approval_policy_instance(self):
        return _approval_from_name(self.approval_policy)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CielConfig":
        default_tenant = data.get("default_tenant") or os.getenv("CIEL_TENANT")
        approval_policy = data.get("approval_policy", "manual") or os.getenv(
            "CIEL_APPROVAL_POLICY", "manual"
        )
        providers: List[ProviderEntry] = [
            ProviderEntry.from_dict(entry)
            for entry in data.get("providers", []) or []
        ]
        tenants: List[str] = list(data.get("tenants", []) or [])
        audit = AuditConfig.from_dict(data.get("audit"))
        gateway = GatewayConfig.from_dict(data.get("gateway"))
        return cls(
            default_tenant=default_tenant,
            approval_policy=approval_policy,
            providers=providers,
            tenants=tenants,
            audit=audit,
            gateway=gateway,
        )

    @classmethod
    def load(cls, path: str = "ciel.yaml") -> "CielConfig":
        """Load a ciel.yaml manifesto, falling back to env-only if absent.

        Raises ``ImportError`` if PyYAML is not installed but a manifesto file
        exists.
        """
        if not os.path.exists(path):
            # Offline / env-only boot is allowed.
            return cls(
                default_tenant=os.getenv("CIEL_TENANT"),
                approval_policy=os.getenv("CIEL_APPROVAL_POLICY", "manual"),
            )
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "PyYAML is required to load ciel.yaml (uv pip install pyyaml)"
            ) from exc
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)


def _build_echo_provider() -> ChatProvider:
    """Offline echo provider, reused from the gateway server module."""
    from ciel.gateway.server import _EchoProvider

    return _EchoProvider()


def _build_audit_sink(audit: AuditConfig):
    """Resolve the configured audit sink."""
    from ciel.observability import InMemoryAuditSink, JsonlAuditSink, NullAuditSink

    driver = (audit.driver or "null").lower()
    if driver in ("jsonl",):
        return JsonlAuditSink(base_path=audit.path or "audit")
    if driver in ("otel",):
        # OTEL driver is not wired into a live exporter here; fall back to an
        # in-memory sink so the runtime stays functional and testable.
        return InMemoryAuditSink()
    return NullAuditSink()


def build_runtime(config: CielConfig) -> DefaultAgentRuntime:
    """Wire a :class:`DefaultAgentRuntime` from a :class:`CielConfig`.

    Provider entries with a ``base_url`` are registered through
    :class:`ProviderFactory` and collected in a :class:`ProviderRegistry`. When
    no providers are configured (or none resolve), a deterministic offline echo
    provider is used so the runtime boots for smoke tests. Multi-tenancy is
    preserved: the tool provider still requires ``tenant_id`` on execution.
    """
    registry = config.provider_registry

    # Choose the primary provider: first registered one, else echo offline.
    if registry.available():
        provider_name = registry.available()[0]
        provider = registry.get(provider_name)
    else:
        provider = _build_echo_provider()

    tool_registry = ToolRegistry(default_toolset="default")
    tool_provider = ToolProvider(registry=tool_registry, require_tenant_on_execution=True)
    dispatcher = DefaultToolDispatcher(provider=tool_provider, default_toolset="default")

    approval_policy = config.approval_policy_instance()
    audit_sink = _build_audit_sink(config.audit)

    return DefaultAgentRuntime(
        provider=provider,
        dispatcher=dispatcher,
        registry=registry,
        audit_sink=audit_sink,
        agent="default",
        approval_policy=approval_policy,
    )


def build_app(config: CielConfig):
    """Compose the full gateway FastAPI app from a :class:`CielConfig`.

    Delegates to :func:`ciel.gateway.server.make_app` with the resolved
    default tenant. Multi-tenancy is enforced by the control plane.
    """
    from ciel.gateway.server import make_app

    return make_app(tenant_id=config.default_tenant)


def load(path: str = "ciel.yaml") -> CielConfig:
    """Module-level convenience wrapper for :meth:`CielConfig.load`."""
    return CielConfig.load(path)


__all__ = [
    "CielConfig",
    "ProviderEntry",
    "AuditConfig",
    "GatewayConfig",
    "load",
    "build_runtime",
    "build_app",
]
