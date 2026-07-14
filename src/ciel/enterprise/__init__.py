"""Enterprise hardening for Ciel (Fase 7): RBAC/OIDC, audit inmutable,
cost governance, secrets y rate-limit transversal.

Todos los módulos son OFFLINE-SAFE y no introducen dependencias duras: OIDC
y Vault son backends opcionales que, de faltar su extra, exponen
``OIDC_AVAILABLE`` / ``VAULT_AVAILABLE`` y lanzan ``FeatureUnavailable`` en
lugar de romper el import.
"""

from __future__ import annotations

from ciel.enterprise.audit import HashChainAuditSink
from ciel.enterprise.cost import (
    BudgetExceededError,
    CostError,
    CostGovernor,
    ModelCost,
)
from ciel.enterprise.rbac import (
    Assignment,
    DEFAULT_ROLES,
    FeatureUnavailable,
    OIDCVerifier,
    RBACEngine,
    RBACError,
    Role,
)
from ciel.enterprise.ratelimit import RateLimitError, TenantRateLimiter
from ciel.enterprise.secrets import (
    EnvSecretBackend,
    FeatureUnavailable as SecretsFeatureUnavailable,
    KubernetesSecretBackend,
    SecretError,
    SecretStore,
    VaultSecretBackend,
)

__all__ = [
    # rbac
    "Role",
    "Assignment",
    "RBACError",
    "FeatureUnavailable",
    "DEFAULT_ROLES",
    "RBACEngine",
    "OIDCVerifier",
    # audit
    "HashChainAuditSink",
    # cost
    "ModelCost",
    "BudgetExceededError",
    "CostError",
    "CostGovernor",
    # secrets
    "SecretError",
    "EnvSecretBackend",
    "KubernetesSecretBackend",
    "VaultSecretBackend",
    "SecretStore",
    # ratelimit
    "RateLimitError",
    "TenantRateLimiter",
]
