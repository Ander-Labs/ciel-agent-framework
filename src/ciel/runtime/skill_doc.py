from __future__ import annotations

"""Skill Doc Auto-Generation (Fase 12 — Item 4).

Offline documentation generation for skills. Given a :class:`ciel.runtime.skills.Skill`
whose ``content`` is Python source, we parse the *first* callable defined in that
source with the :mod:`ast` module and extract its ``name``, argument signature and
docstring. From those we build:

* ``generate_doc(skill) -> dict`` returning ``{"name", "description", "category"}``,
  where ``name``/``description`` come from the callable (name / docstring) and
  ``category`` is preserved verbatim from ``skill.category``.
* ``to_markdown(skill) -> str`` rendering the same information as a markdown
  document with a YAML frontmatter block plus a human-readable body.

Everything is network-free and dependency-free (stdlib ``ast`` only), so the
behaviour can be exercised by offline tests — the same convention as Fases 10–12.
"""

import ast
from typing import Any, Dict, List, Optional, Tuple

from ciel.runtime.skills import Skill


class SkillDocError(Exception):
    """Raised when a skill's content cannot be parsed for documentation."""


def _parse_first_callable(content: str) -> Tuple[str, Optional[str], List[str]]:
    """Parse ``content`` and return ``(name, docstring, args)`` of the first callable.

    A "callable" is the first :class:`ast.FunctionDef` or
    :class:`ast.AsyncFunctionDef` in the module body. The ``args`` list contains
    the positional/keyword argument names (with ``*`` / ``**`` markers for the
    variadic ones). Raises :class:`SkillDocError` for empty/bad/non-callable code.
    """
    if not content or not content.strip():
        raise SkillDocError("skill content is empty")

    try:
        tree = ast.parse(content)
    except SyntaxError as exc:  # noqa: BLE001
        raise SkillDocError(f"skill content has invalid syntax: {exc}") from exc

    node: Optional[ast.AST] = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node = stmt
            break

    if node is None:
        raise SkillDocError("skill content defines no callable to document")

    name = node.name  # type: ignore[attr-defined]
    docstring = ast.get_docstring(node)

    args: List[str] = []
    a = node.args  # type: ignore[attr-defined]
    for pos in a.posonlyargs:
        args.append(pos.arg)
    for arg in a.args:
        args.append(arg.arg)
    if a.vararg:
        args.append("*" + a.vararg.arg)
    for kw in a.kwonlyargs:
        args.append(kw.arg)
    if a.kwarg:
        args.append("**" + a.kwarg.arg)

    return name, docstring, args


def generate_doc(skill: Skill) -> Dict[str, Any]:
    """Build ``{"name", "description", "category"}`` from a skill's compiled code.

    ``name`` and ``description`` are taken from the *first* callable defined in
    ``skill.content`` (its function name and docstring); ``description`` falls
    back to an empty string when the callable has no docstring. ``category`` is
    preserved verbatim from ``skill.category`` (which may be ``None``).
    """
    name, docstring, _ = _parse_first_callable(skill.content)
    return {
        "name": name,
        "description": docstring or "",
        "category": skill.category,
    }


def _yaml_escape_scalar(value: str) -> str:
    """Escape a string so it is safe as a single-line YAML double-quoted scalar."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def to_markdown(skill: Skill) -> str:
    """Render a skill as a markdown string with YAML frontmatter + body.

    The frontmatter carries ``name``, ``description`` and (when present)
    ``category``. The body repeats the title, the full docstring and the
    callable's argument signature, so the generated doc is useful on its own.
    """
    name, docstring, args = _parse_first_callable(skill.content)
    category = skill.category

    frontmatter: List[str] = ["---"]
    frontmatter.append(f"name: {name}")
    frontmatter.append(f'description: "{_yaml_escape_scalar(docstring or "")}"')
    if category is not None:
        frontmatter.append(f"category: {category}")
    frontmatter.append("---")

    body: List[str] = [f"# {name}", ""]
    if docstring:
        body.append(docstring)
        body.append("")
    if category is not None:
        body.append(f"**Category:** {category}")
        body.append("")
    sig = f"{name}({', '.join(args)})" if args else f"{name}()"
    body.append("## Signature")
    body.append("")
    body.append(f"```python\n{sig}\n```")
    body.append("")

    return "\n".join(frontmatter) + "\n" + "\n".join(body)
