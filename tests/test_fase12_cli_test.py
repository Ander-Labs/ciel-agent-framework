"""Fase 12 — CLI `ciel skills` logic (Item 7).

Offline tests (no network, no API keys) covering the pure logic functions in
``ciel.cli.skills_cli``:

  - create + list
  - verify pass
  - verify fail (wrong expectation)
  - remove

Las funciones de lógica reciben la :class:`SkillLibrary` explícitamente, así
que cada test mantiene su propia instancia en memoria y comparte estado entre
llamadas (create -> list / verify / remove) sin tocar el disco.
"""

from __future__ import annotations

import json

import pytest

from ciel.cli.skills_cli import (
    create_skill,
    list_registered,
    remove_skill,
    verify_skill,
)
from ciel.runtime.skills_lib import SkillLibrary, SkillVerificationError

_GOOD_CODE = (
    "def add(a, b):\n"
    '    """Sum two numbers."""\n'
    "    return a + b\n"
)

_BAD_SYNTAX = "def broken(:\n    return 1\n"


@pytest.fixture
def lib():
    return SkillLibrary()


@pytest.fixture
def code_file(tmp_path):
    p = tmp_path / "add_skill.py"
    p.write_text(_GOOD_CODE, encoding="utf-8")
    return str(p)


@pytest.fixture
def bad_code_file(tmp_path):
    p = tmp_path / "broken_skill.py"
    p.write_text(_BAD_SYNTAX, encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# create + list
# --------------------------------------------------------------------------- #
def test_create_then_list(lib, code_file):
    skill = create_skill(
        lib,
        name="add",
        description="sum two ints",
        code_file=code_file,
        category="math",
    )
    assert skill.name == "add"
    assert skill.sha256 is not None

    registered = list_registered(lib)
    names = {s.name for s in registered}
    assert "add" in names
    # category round-trips
    added = next(s for s in registered if s.name == "add")
    assert added.category == "math"
    assert added.description == "sum two ints"


def test_create_invalid_syntax_raises(lib, bad_code_file):
    # SkillLibrary.create_from_code propaga SkillError ante sintaxis inválida.
    from ciel.runtime.skills_lib import SkillError

    with pytest.raises(SkillError):
        create_skill(
            lib,
            name="broken",
            description="bad",
            code_file=bad_code_file,
        )


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def test_verify_pass(lib, code_file):
    create_skill(lib, name="add", description="sum", code_file=code_file)
    result = verify_skill(
        lib,
        name="add",
        test_cases=[
            {"call": {"a": 1, "b": 2}, "expect": 3},
            {"call": {"a": 10, "b": -4}, "expect": 6},
        ],
    )
    assert result.passed is True
    assert result.skill == "add"
    assert result.attempts == 2


def test_verify_fail_wrong_expectation(lib, code_file):
    create_skill(lib, name="add", description="sum", code_file=code_file)
    result = verify_skill(
        lib,
        name="add",
        test_cases=[
            {"call": {"a": 1, "b": 2}, "expect": 999},
        ],
    )
    assert result.passed is False
    assert result.attempts == 1
    assert "expected" in (result.error or "").lower()


def test_verify_unknown_skill_raises(lib):
    with pytest.raises(SkillVerificationError):
        verify_skill(lib, name="does-not-exist", test_cases=[])


# --------------------------------------------------------------------------- #
# remove
# --------------------------------------------------------------------------- #
def test_remove_existing(lib, code_file):
    create_skill(lib, name="add", description="sum", code_file=code_file)
    assert remove_skill(lib, name="add") is True
    assert list_registered(lib) == []
    # remove again -> False (already gone)
    assert remove_skill(lib, name="add") is False


def test_remove_missing_returns_false(lib):
    assert remove_skill(lib, name="nope") is False
