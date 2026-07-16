"""Fase 12 — Item 4: Skill Doc Auto-Generation (offline tests)."""

from __future__ import annotations

from ciel.runtime.skills import Skill
from ciel.runtime.skill_doc import SkillDocError, generate_doc, to_markdown

_CODE = (
    "def add(a, b):\n"
    '    """Sum two numbers."""\n'
    "    return a + b\n"
)

_CODE_NO_DOC = (
    "def mul(x, y):\n"
    "    return x * y\n"
)


def _skill(code=_CODE, category="math"):
    return Skill(name="add", description="", content=code, category=category)


def test_generate_doc_extracts_name_and_description():
    doc = generate_doc(_skill())
    assert doc["name"] == "add"
    assert doc["description"] == "Sum two numbers."
    assert doc["category"] == "math"


def test_generate_doc_no_docstring_falls_back_to_empty():
    doc = generate_doc(_skill(code=_CODE_NO_DOC, category=None))
    assert doc["name"] == "mul"
    assert doc["description"] == ""
    assert doc["category"] is None


def test_generate_doc_preserves_category():
    doc = generate_doc(_skill(category="text"))
    assert doc["category"] == "text"


def test_to_markdown_has_frontmatter():
    md = to_markdown(_skill())
    assert md.startswith("---\n")
    assert "name: add" in md
    assert 'description: "Sum two numbers."' in md
    assert "category: math" in md
    # closes frontmatter
    assert md.index("---\n") != md.rindex("---\n")


def test_to_markdown_includes_signature():
    md = to_markdown(_skill())
    assert "add(a, b)" in md
    assert "# add" in md


def test_to_markdown_omits_category_when_none():
    md = to_markdown(_skill(code=_CODE_NO_DOC, category=None))
    assert "category:" not in md
