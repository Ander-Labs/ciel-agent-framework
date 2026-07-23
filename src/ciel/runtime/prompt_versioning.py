"""Fase 19 — Prompt evolution versionado (Autonomía II, v0.13.0).

Este módulo aporta versionado semántico de *prompts* del agente (instructions
sistemáticas) con persistencia offline en el ``StateBackend`` (SQLite en dev /
Postgres en prod) y aislamiento estricto por ``tenant_id``.

Molde: ``skill_versioning.py`` (Fase 12). A diferencia de los skills (que viven
en memoria dentro de ``SkillLibrary``), los prompts SÍ se persisten en SQLite a
través del ``StateBackend`` para que sobrevivan reinicios y sean auditables.

Todo es network-free y API-key-free (offline-safe).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Errores locales (no dependemos del SkillError de skills).
class PromptVersioningError(Exception):
    """Error de versionado de prompts."""


INITIAL_VERSION = "0.0.0"


@dataclass
class PromptVersion:
    """Versión semántica enriquecida de un prompt del agente.

    Lleva ``major.minor.patch`` + ``changelog`` + ``released_at`` (timestamp) +
    el hash ``sha256`` del texto, y la trazabilidad de linaje
    (``previous_version`` / ``parent``).
    """

    major: int = 0
    minor: int = 0
    patch: int = 0
    name: str = ""
    prompt_text: str = ""
    changelog: str = ""
    released_at: Optional[datetime] = None
    sha256: str = ""
    previous_version: Optional[str] = None
    parent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- serialización ------------------------------------------------------

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, version: str) -> "PromptVersion":
        parts = (version.split(".") + ["0", "0", "0"])[:3]
        try:
            major, minor, patch = (int(p) for p in parts)
        except ValueError as exc:
            raise PromptVersioningError(f"invalid version string: {version!r}") from exc
        return cls(major=major, minor=minor, patch=patch)

    def bump(self, kind: str = "patch") -> "PromptVersion":
        kind = (kind or "patch").lower()
        if kind == "major":
            return PromptVersion(self.major + 1, 0, 0)
        if kind == "minor":
            return PromptVersion(self.major, self.minor + 1, 0)
        if kind == "patch":
            return PromptVersion(self.major, self.minor, self.patch + 1)
        raise PromptVersioningError(f"unknown bump kind: {kind!r} (expected major/minor/patch)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "prompt_text": self.prompt_text,
            "changelog": self.changelog,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "sha256": self.sha256,
            "previous_version": self.previous_version,
            "parent": self.parent,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptVersion":
        ver = cls.parse(data.get("version") or INITIAL_VERSION)
        ver.name = data.get("name", "")
        ver.prompt_text = data.get("prompt_text", "")
        ver.changelog = data.get("changelog", "")
        ver.sha256 = data.get("sha256", "")
        ver.previous_version = data.get("previous_version")
        ver.parent = data.get("parent")
        ver.metadata = data.get("metadata") or {}
        raw = data.get("released_at")
        if raw:
            try:
                ver.released_at = datetime.fromisoformat(raw)
            except (ValueError, TypeError):  # pragma: no cover - defensive
                ver.released_at = None
        return ver


def sha256_text(text: str) -> str:
    """Hash determinista del texto del prompt (offline)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptRegistry:
    """Registro multitenant de prompts versionados sobre un ``StateBackend``.

    El ``backend`` es cualquier instancia de ``ciel.runtime.state_backend.StateBackend``
    (``SqliteStateBackend`` por defecto, ``PostgresStateBackend`` en prod). Todas
    las lecturas/escrituras filtran estrictamente por ``tenant_id``.
    """

    def __init__(self, backend: Any) -> None:
        # backend: ciel.runtime.state_backend.StateBackend
        self._backend = backend

    # --- escritura ----------------------------------------------------------

    def create(
        self,
        name: str,
        prompt_text: str,
        *,
        tenant_id: Optional[str] = None,
        changelog: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PromptVersion:
        """Crea la versión inicial ``0.0.0`` de un prompt.

        Lanza :class:`PromptVersioningError` si el nombre ya existe para el tenant.
        """
        existing = self._backend.prompt_get(tenant_id=tenant_id, name=name)
        if existing is not None:
            raise PromptVersioningError(
                f"el prompt {name!r} ya existe para tenant {tenant_id!r}; usa update()"
            )
        pv = PromptVersion(
            name=name,
            prompt_text=prompt_text,
            changelog=changelog,
            released_at=datetime.now(timezone.utc),
            sha256=sha256_text(prompt_text),
            previous_version=None,
            parent=None,
            metadata=metadata or {},
        )
        self._save(pv, tenant_id=tenant_id)
        return pv

    def update(
        self,
        name: str,
        prompt_text: str,
        *,
        tenant_id: Optional[str] = None,
        bump: str = "patch",
        changelog: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PromptVersion:
        """Bumpea un prompt existente y guarda la nueva versión."""
        current = self.get(name, tenant_id=tenant_id)
        if current is None:
            raise PromptVersioningError(
                f"no existe el prompt {name!r} para tenant {tenant_id!r}; usa create()"
            )
        new_ver = current.bump(bump)
        pv = PromptVersion(
            name=name,
            prompt_text=prompt_text,
            changelog=changelog,
            released_at=datetime.now(timezone.utc),
            sha256=sha256_text(prompt_text),
            previous_version=current.version,
            parent=current.version,
            metadata=metadata or current.metadata or {},
        )
        # conserva el major/minor/patch calculado por bump
        pv.major, pv.minor, pv.patch = new_ver.major, new_ver.minor, new_ver.patch
        self._save(pv, tenant_id=tenant_id)
        return pv

    def _save(self, pv: PromptVersion, *, tenant_id: Optional[str]) -> None:
        self._backend.prompt_save(
            tenant_id=tenant_id,
            name=pv.name,
            version=pv.version,
            prompt_text=pv.prompt_text,
            value_json=_dump(pv.to_dict()),
            sha256=pv.sha256,
            previous_version=pv.previous_version,
            created_at=pv.released_at.isoformat() if pv.released_at else _now_iso(),
        )

    # --- lectura ------------------------------------------------------------

    def get(
        self,
        name: str,
        *,
        tenant_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Optional[PromptVersion]:
        row = self._backend.prompt_get(tenant_id=tenant_id, name=name, version=version)
        if row is None:
            return None
        return PromptVersion.from_dict(row)

    def history(self, name: str, *, tenant_id: Optional[str] = None) -> List[PromptVersion]:
        rows = self._backend.prompt_get_history(tenant_id=tenant_id, name=name)
        return [PromptVersion.from_dict(r) for r in rows]

    def evolution_tree(self, name: str, *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Devuelve el árbol de linaje de un prompt versionado.

        Misma forma que ``skill_versioning.evolution_tree``:

        ``{"name", "root", "lineage": [...], "nodes": {version: {...}}}``
        con ``parent`` / ``children`` / ``sha256`` / ``changelog`` / ``released_at``.
        """
        versions = self.history(name, tenant_id=tenant_id)
        if not versions:
            raise PromptVersioningError(f"unknown prompt: {name!r} (tenant {tenant_id!r})")

        keys: List[str] = [v.version for v in versions]
        nodes: Dict[str, Dict[str, Any]] = {}
        for idx, pv in enumerate(versions):
            key = pv.version
            raw_prev = pv.previous_version
            parent = raw_prev if raw_prev is not None else (keys[idx - 1] if idx > 0 else None)
            nodes[key] = {
                "version": key,
                "parent": parent,
                "previous_version": raw_prev,
                "children": [],
                "sha256": pv.sha256,
                "changelog": pv.changelog,
                "released_at": pv.released_at.isoformat() if pv.released_at else None,
                "prompt_text": pv.prompt_text,
            }

        for key, node in nodes.items():
            if node["parent"] is not None and node["parent"] in nodes:
                nodes[node["parent"]]["children"].append(key)

        roots = [k for k, n in nodes.items() if n["parent"] is None]
        root = roots[0] if roots else (keys[0] if keys else None)
        return {
            "name": name,
            "root": root,
            "lineage": list(keys),
            "nodes": nodes,
        }


def _dump(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:  # pragma: no cover - defensive
        return json.dumps({"repr": repr(value)})


__all__ = [
    "PromptVersioningError",
    "PromptVersion",
    "PromptRegistry",
    "sha256_text",
    "INITIAL_VERSION",
]
