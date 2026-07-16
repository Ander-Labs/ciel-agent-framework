from __future__ import annotations

"""Skill Composition Engine (Fase 12 — Item 3).

Combines N existing :class:`~ciel.runtime.skills.Skill` objects into a single
*new* :class:`Skill` whose ``content`` is a fusion of the source code bodies.
The way the source functions are wired together is controlled by ``combinator``:

* ``"sequence"``  -- call each source function in order, feeding the output of
  one into the next (a pipeline).
* ``"parallel"``  -- call every source function with the same arguments and
  return the list of their results.
* ``"selector"``  -- try each source function in order and return the first
  result that does not raise; raise if all fail.

Everything is network-free and API-key-free (offline, like the rest of Fase 12).
The composed skill can be registered into a passed :class:`SkillLibrary` so it
becomes retrievable via ``library.get(name)``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import ast

from ciel.runtime.skills import Skill
from ciel.runtime.skills_lib import SkillLibrary


class SkillCompositionError(Exception):
    """Raised when a composition cannot be built (e.g. no callables)."""


def _main_callable(content: str, fallback_name: str) -> Optional[str]:
    """Return the name of the primary callable defined in ``content``.

    Preference order: a top-level function matching ``fallback_name`` (usually
    the skill's own name), otherwise the first top-level function definition.
    Returns ``None`` if the code defines no functions.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    funcs: List[str] = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not funcs:
        return None
    if fallback_name in funcs:
        return fallback_name
    return funcs[0]


def _composed_body(name: str, callables: Sequence[str], combinator: str) -> str:
    """Generate the source of the composed function for the given combinator."""
    names = list(callables)
    if combinator == "sequence":
        lines = [f"def {name}(*args, **kwargs):", "    _acc = " + f"{names[0]}(*args, **kwargs)"]
        for fn in names[1:]:
            lines.append(f"    _acc = {fn}(_acc)")
        lines.append("    return _acc")
        return "\n".join(lines)
    if combinator == "parallel":
        tuple_expr = "(" + ", ".join(names) + ")"
        return (
            f"def {name}(*args, **kwargs):\n"
            f"    return [_fn(*args, **kwargs) for _fn in {tuple_expr}]"
        )
    if combinator == "selector":
        tuple_expr = "(" + ", ".join(names) + ")"
        return (
            f"def {name}(*args, **kwargs):\n"
            f"    for _fn in {tuple_expr}:\n"
            f"        try:\n"
            f"            return _fn(*args, **kwargs)\n"
            f"        except Exception:\n"
            f"            continue\n"
            f"    raise RuntimeError(\"all composed skills failed\")"
        )
    raise SkillCompositionError(f"unknown combinator: {combinator!r}")


@dataclass
class SkillComposition:
    """Builds a single composed :class:`Skill` from N source skills."""

    # Optional library the composed skill is registered into (set per-call).
    library: Optional[SkillLibrary] = field(default=None)

    def compose(
        self,
        name: str,
        skills: Sequence[Skill],
        combinator: str,
        *,
        library: Optional[SkillLibrary] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Skill:
        """Fuse ``skills`` into a new :class:`Skill` named ``name``.

        Parameters
        ----------
        name:
            Name of the produced (composed) skill.
        skills:
            Source skills to combine (must be non-empty).
        combinator:
            One of ``"sequence"``, ``"parallel"`` or ``"selector"``.
        library:
            Optional :class:`SkillLibrary` to register the composed skill into.
            If omitted, ``self.library`` (if set at construction) is used.
        description / category:
            Override the auto-generated description / category.

        Returns
        -------
        Skill
            The newly built composed skill (also registered into ``library``
            when one is supplied).
        """
        if not skills:
            raise SkillCompositionError("compose() requires at least one source skill")

        callables: List[str] = []
        for skill in skills:
            main = _main_callable(skill.content, skill.name)
            if main is None:
                raise SkillCompositionError(
                    f"skill '{skill.name}' defines no callable to compose"
                )
            callables.append(main)

        if combinator not in ("sequence", "parallel", "selector"):
            raise SkillCompositionError(
                f"combinator must be 'sequence'|'parallel'|'selector', got {combinator!r}"
            )

        # Fusion: concatenate the source code bodies, then append the composed
        # function that wires the source callables together.
        bodies = "\n\n".join(skill.content.rstrip() for skill in skills)
        composed_fn = _composed_body(name, callables, combinator)
        content = f"{bodies}\n\n\n{composed_fn}\n"

        # Syntax-check the fused module before handing it back.
        try:
            compile(content, f"<composed:{name}>", "exec")
        except SyntaxError as exc:  # noqa: BLE001
            raise SkillCompositionError(
                f"composed skill '{name}' has invalid syntax: {exc}"
            ) from exc

        source_names = [s.name for s in skills]
        metadata: Dict[str, Any] = {
            "composition": {
                "combinator": combinator,
                "source_skills": source_names,
                "source_callables": dict(zip(source_names, callables)),
            },
            "combinator": combinator,
            "source_skills": source_names,
            "composed_callable": name,
        }

        composed = Skill(
            name=name,
            description=description
            or f"Composed skill '{name}' combining {source_names} via {combinator}.",
            content=content,
            category=category if category is not None else (skills[0].category),
            metadata=metadata,
        )

        target = library if library is not None else self.library
        if target is not None:
            target.register(composed)

        return composed
