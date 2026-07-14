"""RBAC engine + OIDC verifier (offline-safe, no hard deps).

Firmas según FASE7_DESIGN.md sección 2.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class Role:
    name: str
    permissions: frozenset[str]  # acciones tipo "agent:run", "tools:exec", "admin:*"


@dataclass
class Assignment:
    subject: str
    role: str
    tenant_id: Optional[str] = None


class RBACError(Exception):
    ...


class FeatureUnavailable(Exception):
    """OIDC sin deps disponibles."""
    ...


DEFAULT_ROLES: dict[str, Role] = {
    "admin": Role("admin", frozenset({"agent:*", "tools:*", "admin:*", "board:*", "cost:*", "approve:*"})),
    "operator": Role("operator", frozenset({"agent:run", "tools:exec", "board:write"})),
    "viewer": Role("viewer", frozenset({"agent:read", "board:read"})),
}


def _permission_matches(permissions: frozenset[str], action: str) -> bool:
    """Coincide si hay permiso exacto o prefijo 'category:*'."""
    if action in permissions:
        return True
    if ":" in action:
        category = action.split(":", 1)[0]
        if f"{category}:*" in permissions:
            return True
    return False


class RBACEngine:
    def __init__(self, *, tenant_id=None, roles=None, assignments=None):
        self.tenant_id = tenant_id
        # roles: mezcla DEFAULT_ROLES con los dados
        self.roles: dict[str, Role] = dict(DEFAULT_ROLES)
        if roles:
            self.roles.update(roles)
        # assignments: dict[(tenant_id or "*", subject)] -> role
        self._assignments: dict[tuple[str, str], str] = {}
        if assignments:
            if isinstance(assignments, dict):
                for key, role in assignments.items():
                    self._assignments[key] = role
            else:
                for a in assignments:
                    key = (a.tenant_id or "*", a.subject)
                    self._assignments[key] = a.role

    def assign(self, subject: str, role_name: str, *, tenant_id=None) -> None:
        self._assignments[(tenant_id or "*", subject)] = role_name

    def revoke(self, subject: str, *, tenant_id=None) -> None:
        self._assignments.pop((tenant_id or "*", subject), None)

    def role_of(self, subject: str, *, tenant_id=None) -> Optional[str]:
        # asignación específica de tenant > asignación global ("*") > None
        if tenant_id is not None:
            role = self._assignments.get((tenant_id, subject))
            if role is not None:
                return role
        role = self._assignments.get(("*", subject))
        if role is not None:
            return role
        return None

    def has_permission(self, subject: str, action: str, *, tenant_id=None) -> bool:
        role_name = self.role_of(subject, tenant_id=tenant_id)
        if role_name is None:
            return False
        role = self.roles.get(role_name)
        if role is None:
            return False
        return _permission_matches(role.permissions, action)

    def check(self, subject: str, action: str, *, tenant_id=None) -> None:
        if not self.has_permission(subject, action, tenant_id=tenant_id):
            raise RBACError(
                f"subject '{subject}' no autorizado para '{action}'"
                f" (tenant={tenant_id})"
            )

    def list_roles(self) -> list[str]:
        return sorted(self.roles.keys())

    def snapshot(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "roles": {
                name: sorted(role.permissions) for name, role in self.roles.items()
            },
            "assignments": {
                f"{k[0]}\x1f{k[1]}": v for k, v in self._assignments.items()
            },
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> "RBACEngine":
        roles = {
            name: Role(name, frozenset(perms))
            for name, perms in data.get("roles", {}).items()
        }
        assignments: dict[tuple[str, str], str] = {}
        for key, role in data.get("assignments", {}).items():
            tid, subject = key.split("\x1f", 1)
            assignments[(tid, subject)] = role
        return cls(
            tenant_id=data.get("tenant_id"),
            roles=roles,
            assignments=assignments,
        )


def _detect_oidc() -> bool:
    try:
        import importlib
        importlib.import_module("jwt")
        return True
    except Exception:
        return False


class OIDCVerifier:
    OIDC_AVAILABLE: bool = _detect_oidc()

    def __init__(self, *, issuer=None, audience=None, jwks_uri=None, public_key=None):
        self.issuer = issuer
        self.audience = audience
        self.jwks_uri = jwks_uri
        self.public_key = public_key

    def verify(self, token: str) -> dict:
        if not self.OIDC_AVAILABLE:
            raise FeatureUnavailable(
                "OIDC no disponible: instala PyJWT/cryptography"
            )
        import jwt  # type: ignore

        options = {"verify_aud": self.audience is not None}
        claims = jwt.decode(
            token,
            self.public_key,
            algorithms=["RS256", "HS256", "ES256"],
            audience=self.audience,
            issuer=self.issuer,
            options=options,
        )
        return claims
