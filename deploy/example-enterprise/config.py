"""Carga de configuración central del gateway Ciel (ciel.yaml).

Permite unir en un solo manifesto de deploy: proveedores, tenant por defecto
y políticas de aprobación. Es un loader ligero (yaml + env) sin dependencias
obligatorias del runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ProviderConfigEntry:
    name: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    default_model: Optional[str] = None
    tenant: Optional[str] = None

    @property
    def api_key(self) -> Optional[str]:
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderConfigEntry":
        return cls(
            name=data["name"],
            base_url=data.get("base_url"),
            api_key_env=data.get("api_key_env"),
            default_model=data.get("default_model"),
            tenant=data.get("tenant"),
        )


@dataclass
class GatewayConfig:
    default_tenant: Optional[str] = None
    approval_policy: str = "manual"
    providers: Dict[str, ProviderConfigEntry] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GatewayConfig":
        default_tenant = data.get("default_tenant") or os.getenv("CIEL_TENANT")
        approval_policy = data.get("approval_policy", "manual")
        providers: Dict[str, ProviderConfigEntry] = {}
        for entry in data.get("providers", []) or []:
            p = ProviderConfigEntry.from_dict(entry)
            providers[p.name] = p
        return cls(default_tenant=default_tenant, approval_policy=approval_policy, providers=providers)

    @classmethod
    def load(cls, path: str = "ciel.yaml") -> "GatewayConfig":
        if not os.path.exists(path):
            # Fallback a variables de entorno (arranque offline permitido).
            return cls(
                default_tenant=os.getenv("CIEL_TENANT"),
                approval_policy=os.getenv("CIEL_APPROVAL_POLICY", "manual"),
            )
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ImportError("PyYAML requerido para ciel.yaml (uv pip install pyyaml)") from exc
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)


__all__ = ["GatewayConfig", "ProviderConfigEntry"]
