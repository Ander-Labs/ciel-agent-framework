from __future__ import annotations

"""Fase 12 — Skill Versioning + changelog + evolution tree (Item 2).

This module layers *rich* versioning metadata on top of the existing
:class:`~ciel.runtime.skills_lib.SkillLibrary` facade (Fase 12, Item 1) **without
monkey-patching it**. Every helper takes a :class:`SkillLibrary` instance and
operates on the skills it already stores: it reads ``history(name)`` and writes
into each :class:`~ciel.runtime.skills.Skill`'s ``metadata`` dict. The low-level
``Skill`` / ``SkillRegistry`` contract is never touched.

Everything is network-free and API-key-free (offline, same convention as Fases
10-12).

The :func:`evolution_tree` helper is the seed of Ciel's unique **Skill Evolution
Tree**: a lineage structure that records, for every version of a skill, who its
parent was (``previous_version``), so an autonomous agent can visualise how a
skill evolved, branch and roll back.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ciel.runtime.skills import Skill
from ciel.runtime.skills_lib import SkillError, SkillLibrary

# Implicit version key used for a skill that has not (yet) been assigned an
# explicit semantic version by the library (e.g. the very first
# ``create_from_code()`` call, whose metadata carries no ``version`` field).
INITIAL_VERSION = "0.0.0"


@dataclass
class SkillVersion:
    """Enriched semantic version for a single skill release.

    Carries ``major.minor.patch`` plus the human changelog text and the release
    timestamp (``released_at``) — the extra fields that turn a bare ``"0.1.0"``
    string into a first-class, reviewable release record.
    """

    major: int = 0
    minor: int = 0
    patch: int = 0
    changelog: str = ""
    released_at: Optional[datetime] = None

    # --- construction / serialisation ------------------------------------

    @property
    def version(self) -> str:
        """``"major.minor.patch"`` string."""
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, version: str) -> "SkillVersion":
        """Build a :class:`SkillVersion` from a ``"major.minor.patch"`` string."""
        parts = (version.split(".") + ["0", "0", "0"])[:3]
        try:
            major, minor, patch = (int(p) for p in parts)
        except ValueError as exc:
            raise SkillError(f"invalid version string: {version!r}") from exc
        return cls(major=major, minor=minor, patch=patch)

    def bump(self, kind: str = "patch") -> "SkillVersion":
        """Return a new :class:`SkillVersion` bumped by ``major``/``minor``/``patch``."""
        kind = (kind or "patch").lower()
        if kind == "major":
            return SkillVersion(self.major + 1, 0, 0)
        if kind == "minor":
            return SkillVersion(self.major, self.minor + 1, 0)
        if kind == "patch":
            return SkillVersion(self.major, self.minor, self.patch + 1)
        raise SkillError(f"unknown bump kind: {kind!r} (expected major/minor/patch)")

    @classmethod
    def from_skill(cls, skill: Skill) -> "SkillVersion":
        """Build a :class:`SkillVersion` from a stored :class:`Skill`."""
        ver = cls.parse(_version_key(skill))
        ver.changelog = skill.metadata.get("changelog") or ""
        raw = skill.metadata.get("released_at")
        if raw:
            if isinstance(raw, datetime):
                ver.released_at = raw
            else:
                try:
                    ver.released_at = datetime.fromisoformat(raw)
                except (ValueError, TypeError):
                    ver.released_at = None
        return ver


def _version_key(skill: Skill) -> str:
    """Normalised version key for a stored skill (initial == ``"0.0.0"``)."""
    return skill.metadata.get("version") or INITIAL_VERSION


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_changelog(lib: SkillLibrary, name: str, version: str, text: str) -> SkillVersion:
    """Attach a changelog ``text`` to a specific ``version`` of skill ``name``.

    The changelog (and, if absent, the ``released_at`` timestamp) is written into
    the matching :class:`Skill`'s ``metadata`` inside the passed library. The
    function returns the enriched :class:`SkillVersion` for that release.

    Raises :class:`SkillError` if the skill or the requested version is unknown,
    or if ``text`` is empty.
    """
    if not text:
        raise SkillError("changelog text must be a non-empty string")
    history = lib.history(name)
    if not history:
        raise SkillError(f"unknown skill: {name!r}")
    target: Optional[Skill] = None
    for skill in history:
        if _version_key(skill) == version:
            target = skill
            break
    if target is None:
        available = ", ".join(_version_key(s) for s in history)
        raise SkillError(f"skill {name!r} has no version {version!r} (available: {available})")
    target.metadata["changelog"] = text
    target.metadata.setdefault("released_at", _now_iso())
    return SkillVersion.from_skill(target)


def changelog(lib: SkillLibrary, name: str) -> Dict[str, str]:
    """Return ``{version: changelog_text}`` for every version of ``name``.

    Versions are ordered oldest-first (matching ``lib.history``). The initial
    version is keyed ``"0.0.0"`` when the library has not assigned an explicit
    semantic version yet.
    """
    out: Dict[str, str] = {}
    for skill in lib.history(name):
        out[_version_key(skill)] = skill.metadata.get("changelog") or ""
    return out


def evolution_tree(lib: SkillLibrary, name: str) -> Dict[str, Any]:
    """Return the lineage / evolution tree of skill ``name``.

    The result is the seed of Ciel's unique **Skill Evolution Tree**: it records,
    for every version, its parent (``previous_version``) so the autonomous agent
    can see how a skill evolved / branched.

    Structure::

        {
          "name": <skill name>,
          "root": <version key of the base of the lineage>,
          "lineage": [root, ..., latest],          # ordered oldest -> newest
          "nodes": {
             <version>: {
                "version": <version>,
                "parent": <parent version or None>,
                "previous_version": <raw library value>,
                "children": [<child version>, ...],
                "sha256": <hash>,
                "changelog": <text>,
                "released_at": <iso string or None>,
             },
             ...
          },
        }

    The ``parent`` link is *normalised* so the very first ``update()`` (whose
    ``previous_version`` is ``None`` because the initial skill had no explicit
    version) is still chained to its true parent in history order.
    """
    history = lib.history(name)
    if not history:
        raise SkillError(f"unknown skill: {name!r}")

    keys: List[str] = [_version_key(s) for s in history]
    nodes: Dict[str, Dict[str, Any]] = {}
    for idx, skill in enumerate(history):
        key = keys[idx]
        raw_prev = skill.metadata.get("previous_version")
        # Normalise the parent link: a None previous_version that is not the
        # first node chains to its predecessor (fixes the first-update quirk).
        parent = raw_prev if raw_prev is not None else (keys[idx - 1] if idx > 0 else None)
        nodes[key] = {
            "version": key,
            "parent": parent,
            "previous_version": raw_prev,
            "children": [],
            "sha256": skill.sha256,
            "changelog": skill.metadata.get("changelog") or "",
            "released_at": skill.metadata.get("released_at"),
        }

    # Build children lists from the (normalised) parent links.
    for key, node in nodes.items():
        if node["parent"] is not None and node["parent"] in nodes:
            nodes[node["parent"]]["children"].append(key)

    roots = [key for key, node in nodes.items() if node["parent"] is None]
    root = roots[0] if roots else (keys[0] if keys else None)
    lineage = list(keys)  # history order is the linear lineage

    return {
        "name": name,
        "root": root,
        "lineage": lineage,
        "nodes": nodes,
    }
