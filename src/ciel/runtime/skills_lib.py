from __future__ import annotations

"""Dynamic Skill Library + offline verification (Fase 12 — Autonomy I).

This is a *facade* over the existing passive :mod:`ciel.runtime.skills` loader
(``Skill`` / ``SkillRegistry``). It does NOT change the low-level contract:
``Skill`` and ``SkillRegistry`` keep working exactly as before. ``SkillLibrary``
adds a writable, in-memory store on top, and ``SkillVerifier`` adds offline
self-verification (syntax check + executable test cases) so an agent can vet a
skill before trusting it.

Everything here is network-free and API-key-free so it can be exercised by
offline tests (the same convention as Fases 10/11).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ciel.runtime.skills import Skill, SkillRegistry


class SkillError(Exception):
    """Base error for skill library operations."""


class SkillVerificationError(SkillError):
    """Raised when a skill fails verification."""


@dataclass
class SkillVerificationResult:
    """Outcome of :meth:`SkillVerifier.verify`."""

    passed: bool
    skill: str
    attempts: int = 0
    error: Optional[str] = None
    traceback: Optional[str] = None
    expected: Optional[Any] = None
    got: Optional[Any] = None


@dataclass
class SkillVersion:
    """A single immutable version entry stored in the library history."""

    version: str
    sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillLibrary:
    """Writable, in-memory skill store that wraps a :class:`SkillRegistry`.

    The registry remains the source of truth for disk-loaded skills; the
    library layer adds creation, registration, update (with version bump) and
    removal of skills that live only in memory. Tenant isolation is supported
    via the optional ``tenant_id`` key on each stored :class:`Skill`.
    """

    def __init__(self, registry: Optional[SkillRegistry] = None) -> None:
        self.registry = registry or SkillRegistry()
        # name -> list of Skill (newest last). We keep a list so update() can
        # preserve previous_versions for the evolution tree.
        self._skills: Dict[str, List[Skill]] = {}

    # -- backed by the passive registry (backward-compatible) -----------------

    def load_from_disk(self) -> List[Skill]:
        """Discover skills from the registry roots and index them in-memory."""
        found = self.registry.discover()
        for skill in found:
            self._skills.setdefault(skill.name, []).append(skill)
        return found

    # -- writable store --------------------------------------------------------

    def _sha256(self, content: str) -> str:
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def create_from_code(
        self,
        *,
        name: str,
        description: str,
        code: str,
        category: Optional[str] = None,
        tenant_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        """Compile ``code`` (syntax check) and store it as a new skill.

        Raises :class:`SkillError` if the code does not compile. The skill is
        NOT executed here — execution belongs to :class:`SkillVerifier`.
        """
        try:
            compile(code, f"<skill:{name}>", "exec")
        except SyntaxError as exc:  # noqa: BLE001
            raise SkillError(f"skill '{name}' has invalid syntax: {exc}") from exc

        content = code
        skill = Skill(
            name=name,
            description=description,
            content=content,
            category=category,
            metadata={
                **(metadata or {}),
                **({"tenant_id": tenant_id} if tenant_id else {}),
                "sha256": self._sha256(content),
            },
            sha256=self._sha256(content),
        )
        self._skills.setdefault(name, []).append(skill)
        return skill

    def register(self, skill: Skill) -> Skill:
        """Register an already-built :class:`Skill` (e.g. disk-loaded)."""
        if skill.sha256 is None:
            skill.sha256 = self._sha256(skill.content)
        self._skills.setdefault(skill.name, []).append(skill)
        return skill

    def get(self, name: str) -> Optional[Skill]:
        versions = self._skills.get(name)
        if not versions:
            # Fall back to the disk registry (backward-compat lookup).
            return self.registry.get(name)
        return versions[-1]

    def list_skills(self, *, category: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Skill]:
        out: List[Skill] = []
        for versions in self._skills.values():
            latest = versions[-1]
            if category is not None and latest.category != category:
                continue
            if tenant_id is not None and latest.metadata.get("tenant_id") != tenant_id:
                continue
            out.append(latest)
        # Also include any registry-only skills not yet indexed in memory.
        for skill in self.registry.list_skills(category=category):
            if skill.name not in self._skills:
                if tenant_id is None or skill.metadata.get("tenant_id") == tenant_id:
                    out.append(skill)
        return out

    def history(self, name: str) -> List[Skill]:
        """Return every stored version of ``name`` (oldest first)."""
        return list(self._skills.get(name, []))

    def remove(self, name: str) -> bool:
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def update(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        code: Optional[str] = None,
        category: Optional[str] = None,
        bump: str = "patch",
    ) -> Skill:
        """Create a new version of an existing skill, preserving history.

        ``bump`` is one of ``major``/``minor``/``patch`` (semantic) and is
        recorded in ``metadata.version``. The previous version is preserved in
        ``history(name)``.
        """
        versions = self._skills.get(name)
        if not versions:
            disk = self.registry.get(name)
            if disk is None:
                raise SkillError(f"cannot update unknown skill '{name}'")
            versions = [disk]
            self._skills[name] = versions

        previous = versions[-1]
        if code is None:
            code = previous.content
        else:
            try:
                compile(code, f"<skill:{name}>", "exec")
            except SyntaxError as exc:  # noqa: BLE001
                raise SkillError(f"skill '{name}' update has invalid syntax: {exc}") from exc

        new_version = self._next_version(previous.metadata.get("version"), bump)
        updated = Skill(
            name=name,
            description=description if description is not None else previous.description,
            content=code,
            category=category if category is not None else previous.category,
            metadata={
                **previous.metadata,
                "version": new_version,
                "previous_version": previous.metadata.get("version"),
                "sha256": self._sha256(code),
            },
            sha256=self._sha256(code),
        )
        versions.append(updated)
        return updated

    @staticmethod
    def _next_version(current: Optional[str], bump: str) -> str:
        major, minor, patch = (0, 0, 0)
        if current:
            parts = (current.split(".") + ["0", "0", "0"])[:3]
            try:
                major, minor, patch = (int(p) for p in parts)
            except ValueError:
                major, minor, patch = (0, 0, 0)
        if bump == "major":
            major, minor, patch = major + 1, 0, 0
        elif bump == "minor":
            minor, patch = minor + 1, 0
        else:
            patch += 1
        return f"{major}.{minor}.{patch}"


class SkillVerifier:
    """Offline verifier: syntax check + executable test cases.

    A test case is a dict ``{"call": {...}, "expect": <value>}``. The verifier
    executes the skill code in an isolated namespace, looks up a callable named
    after the skill (or the first callable defined), invokes it with ``call``
    arguments and compares the result to ``expect``.
    """

    def __init__(self, library: Optional[SkillLibrary] = None) -> None:
        self.library = library

    def _resolve_callable(self, skill: Skill, namespace: Dict[str, Any]) -> Any:
        if skill.name in namespace and callable(namespace[skill.name]):
            return namespace[skill.name]
        callables = [v for v in namespace.values() if callable(v) and not v.__module__ == "builtins"]
        if not callables:
            raise SkillVerificationError(f"skill '{skill.name}' defines no callable to invoke")
        return callables[0]

    def verify(self, skill: Skill, *, test_cases: Sequence[Dict[str, Any]]) -> SkillVerificationResult:
        # 1) Syntax validation first.
        try:
            compile(skill.content, f"<skill:{skill.name}>", "exec")
        except SyntaxError as exc:  # noqa: BLE001
            return SkillVerificationResult(
                passed=False,
                skill=skill.name,
                attempts=0,
                error=f"syntax error: {exc}",
                traceback=str(exc),
            )

        namespace: Dict[str, Any] = {}
        try:
            exec(skill.content, namespace)  # noqa: S102 — offline, trusted-by-construction
        except Exception as exc:  # noqa: BLE001
            return SkillVerificationResult(
                passed=False,
                skill=skill.name,
                attempts=0,
                error=f"load error: {type(exc).__name__}: {exc}",
                traceback=repr(exc),
            )

        fn = self._resolve_callable(skill, namespace)

        last_traceback: Optional[str] = None
        for attempt, case in enumerate(test_cases, start=1):
            call_args = case.get("call", {}) or {}
            expected = case.get("expect")
            try:
                got = fn(**call_args)
            except Exception as exc:  # noqa: BLE001
                last_traceback = repr(exc)
                return SkillVerificationResult(
                    passed=False,
                    skill=skill.name,
                    attempts=attempt,
                    error=f"case {attempt} raised {type(exc).__name__}: {exc}",
                    traceback=last_traceback,
                    expected=expected,
                )
            if got != expected:
                return SkillVerificationResult(
                    passed=False,
                    skill=skill.name,
                    attempts=attempt,
                    error=f"case {attempt}: expected {expected!r}, got {got!r}",
                    expected=expected,
                    got=got,
                )
        return SkillVerificationResult(
            passed=True,
            skill=skill.name,
            attempts=len(test_cases),
        )

    def verify_by_name(self, name: str, *, test_cases: Sequence[Dict[str, Any]]) -> SkillVerificationResult:
        if self.library is None:
            raise SkillVerificationError("SkillVerifier was built without a library; pass the skill directly")
        skill = self.library.get(name)
        if skill is None:
            raise SkillVerificationError(f"unknown skill '{name}'")
        return self.verify(skill, test_cases=test_cases)
