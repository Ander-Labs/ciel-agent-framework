"""RBAC engine + OIDC verifier (offline-safe, no hard deps).

Firmas según FASE7_DESIGN.md sección 2.1.
"""
from __future__ import annotations

import os
import time
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


# Algoritmos asimétricos aceptados en modo JWKS. Se rechaza explícitamente
# ``none`` y ``HS256`` cuando hay JWKS (mitiga alg-confusion).
_JWKS_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

# Mapeo por defecto de claims → rol para los IdP más comunes. El primer claim
# presente decide; los valores se comparan contra ``role_mapping`` (case-insensitive).
_DEFAULT_ROLE_CLAIMS = ("realm_access.roles", "roles", "groups")

# Mapeo por defecto de valores de claim → rol RBAC de Ciel.
_DEFAULT_ROLE_MAPPING = {
    "admin": "admin",
    "ciel-admin": "admin",
    "administrator": "admin",
    "operator": "operator",
    "ciel-operator": "operator",
    "editor": "operator",
    "viewer": "viewer",
    "ciel-viewer": "viewer",
    "reader": "viewer",
}


def _dig(claims: dict, dotted: str):
    """Extrae un valor de ``claims`` por ruta con puntos (p.ej. realm_access.roles)."""
    cur = claims
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def map_oidc_claims_to_role(
    claims: dict,
    *,
    role_claims: Iterable[str] = _DEFAULT_ROLE_CLAIMS,
    role_mapping: Optional[dict] = None,
) -> Optional[str]:
    """Mapea los claims de un JWT OIDC a un rol RBAC de Ciel.

    Recorre ``role_claims`` en orden; el primer claim presente cuyos valores
    (str o lista) casen con ``role_mapping`` determina el rol. Devuelve ``None``
    si ningún valor mapea (fail-closed: sin rol => sin permisos).

    Soporta el formato de Keycloak (``realm_access.roles``), Auth0/genérico
    (``roles``/``groups``), Azure AD (``roles``/``groups``) y Okta (``groups``).
    """
    mapping = {k.lower(): v for k, v in (role_mapping or _DEFAULT_ROLE_MAPPING).items()}
    for claim in role_claims:
        raw = _dig(claims, claim)
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for value in values:
            if not isinstance(value, str):
                continue
            mapped = mapping.get(value.lower())
            if mapped is not None:
                return mapped
    return None


class OIDCVerifier:
    """Verificador de tokens OIDC/JWT, offline-safe.

    Dos modos de operación:

    * **Local (por defecto)**: valida con una ``public_key`` estática (o secreto
      HS256). Mantiene retrocompatibilidad total con la Fase 7.
    * **JWKS (opt-in)**: descubre el ``jwks_uri`` del IdP (vía ``.well-known/
      openid-configuration`` o URI explícita), cachea las claves JWKS, y valida
      ``iss``/``aud``/``exp``/``alg``. Requiere ``httpx`` y ``PyJWT[crypto]``.

    Todo el trabajo de red es perezoso: construir el verificador nunca hace
    peticiones. Si faltan las deps, ``verify`` lanza ``FeatureUnavailable``.
    """

    OIDC_AVAILABLE: bool = _detect_oidc()

    def __init__(
        self,
        *,
        issuer=None,
        audience=None,
        jwks_uri=None,
        public_key=None,
        role_claims: Optional[Iterable[str]] = None,
        role_mapping: Optional[dict] = None,
        jwks_cache_ttl: float = 3600.0,
        http_client=None,
    ):
        self.issuer = issuer
        self.audience = audience
        self.jwks_uri = jwks_uri
        self.public_key = public_key
        self.role_claims = tuple(role_claims) if role_claims else _DEFAULT_ROLE_CLAIMS
        self.role_mapping = role_mapping
        self.jwks_cache_ttl = jwks_cache_ttl
        self._http_client = http_client
        # cache: {kid: signing_key}
        self._jwks_cache: dict = {}
        self._jwks_fetched_at: float = 0.0

    @classmethod
    def from_config(cls, config: Optional[dict] = None) -> "OIDCVerifier":
        """Construye un verificador desde dict/env.

        Precedencia: valores explícitos en ``config`` > variables de entorno
        ``CIEL_OIDC_*``. Devuelve un verificador siempre (offline-safe); solo
        ``verify`` fallará si faltan deps o no hay clave/JWKS.
        """
        cfg = dict(config or {})

        def pick(key, env, default=None):
            if key in cfg and cfg[key] is not None:
                return cfg[key]
            return os.getenv(env, default)

        role_mapping = cfg.get("role_mapping")
        if role_mapping is None:
            raw = os.getenv("CIEL_OIDC_ROLE_MAPPING")
            if raw:
                # formato "claimvalue:role,claimvalue2:role2"
                role_mapping = {}
                for pair in raw.split(","):
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        role_mapping[k.strip()] = v.strip()

        role_claim = pick("role_claim", "CIEL_OIDC_ROLE_CLAIM")
        role_claims = cfg.get("role_claims")
        if role_claims is None and role_claim:
            role_claims = [role_claim]

        return cls(
            issuer=pick("issuer", "CIEL_OIDC_ISSUER"),
            audience=pick("audience", "CIEL_OIDC_AUDIENCE"),
            jwks_uri=pick("jwks_uri", "CIEL_OIDC_JWKS_URI"),
            public_key=cfg.get("public_key"),
            role_claims=role_claims,
            role_mapping=role_mapping,
        )

    @staticmethod
    def enabled_from_env() -> bool:
        """True si OIDC real está activado por env (``CIEL_OIDC_ENABLED``)."""
        return os.getenv("CIEL_OIDC_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}

    def _client(self):
        if self._http_client is not None:
            return self._http_client
        import httpx  # type: ignore

        return httpx.Client(timeout=10.0)

    def _discover_jwks_uri(self) -> str:
        if self.jwks_uri:
            return self.jwks_uri
        if not self.issuer:
            raise FeatureUnavailable("OIDC JWKS: falta 'issuer' o 'jwks_uri'")
        well_known = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
        client = self._client()
        resp = client.get(well_known)
        resp.raise_for_status()
        uri = resp.json().get("jwks_uri")
        if not uri:
            raise FeatureUnavailable("OIDC discovery no expone 'jwks_uri'")
        self.jwks_uri = uri
        return uri

    def _get_signing_key(self, token: str):
        """Obtiene la clave de firma para el ``kid`` del token, con cache/refresh."""
        import jwt  # type: ignore

        now = time.time()
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        cache_valid = (now - self._jwks_fetched_at) < self.jwks_cache_ttl
        if not cache_valid or (kid and kid not in self._jwks_cache):
            self._refresh_jwks()

        if kid is None:
            # Sin kid: si hay una sola clave, úsala.
            if len(self._jwks_cache) == 1:
                return next(iter(self._jwks_cache.values()))
            raise FeatureUnavailable("token sin 'kid' y JWKS con múltiples claves")
        key = self._jwks_cache.get(kid)
        if key is None:
            raise FeatureUnavailable(f"'kid' desconocido en JWKS: {kid}")
        return key

    def _refresh_jwks(self) -> None:
        from jwt import PyJWKClient  # type: ignore

        uri = self._discover_jwks_uri()
        jwk_client = PyJWKClient(uri)
        # PyJWKClient maneja su propia cache; almacenamos por kid para el guard.
        jwks = jwk_client.get_jwk_set()
        cache = {}
        for key in jwks.keys:
            if key.key_id:
                cache[key.key_id] = key.key
        self._jwks_cache = cache
        self._jwks_fetched_at = time.time()
        self._jwk_client = jwk_client

    def verify(self, token: str) -> dict:
        if not self.OIDC_AVAILABLE:
            raise FeatureUnavailable(
                "OIDC no disponible: instala PyJWT/cryptography"
            )
        import jwt  # type: ignore

        # Modo JWKS (opt-in): hay jwks_uri o (issuer sin public_key local).
        use_jwks = bool(self.jwks_uri) or (self.issuer and self.public_key is None)
        if use_jwks:
            signing_key = self._get_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=_JWKS_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"verify_aud": self.audience is not None},
            )
            return claims

        # Modo local (retrocompat Fase 7).
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

    def verify_and_map_role(self, token: str) -> tuple[dict, Optional[str]]:
        """Verifica el token y devuelve ``(claims, rol_rbac)``.

        El ``subject`` para RBAC es ``claims['sub']``. El rol se deriva vía
        :func:`map_oidc_claims_to_role` con la config del verificador.
        """
        claims = self.verify(token)
        role = map_oidc_claims_to_role(
            claims,
            role_claims=self.role_claims,
            role_mapping=self.role_mapping,
        )
        return claims, role
