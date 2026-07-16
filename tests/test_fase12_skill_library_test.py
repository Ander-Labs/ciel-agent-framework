"""Fase 12 — Dynamic Skill Library + offline verification (Item 1).

Offline tests (no network, no API keys) covering the facade over
``ciel.runtime.skills.SkillRegistry``.
"""

from __future__ import annotations

import pytest

from ciel.runtime import (
    SkillError,
    SkillLibrary,
    SkillVerificationError,
    SkillVerificationResult,
    SkillVerifier,
)
from ciel.runtime.skills import Skill, SkillRegistry


_GOOD_CODE = (
    "def add(a, b):\n"
    "    \"\"\"Sum two numbers.\"\"\"\n"
    "    return a + b\n"
)

_BAD_SYNTAX = "def broken(:\n    return 1\n"


def _make_skill(name="add", code=_GOOD_CODE, **kw):
    lib = SkillLibrary()
    return lib, lib.create_from_code(name=name, description="sum", code=code, **kw)


def test_create_from_code_stores_skill_and_sha():
    lib, skill = _make_skill()
    assert skill.name == "add"
    assert skill.sha256 is not None
    assert len(skill.sha256) == 64
    # available via get()
    assert lib.get("add") is skill


def test_create_from_code_rejects_bad_syntax():
    lib = SkillLibrary()
    with pytest.raises(SkillError):
        lib.create_from_code(name="bad", description="x", code=_BAD_SYNTAX)


def test_register_and_list_skills():
    lib = SkillLibrary()
    s = Skill(name="greet", description="hi", content="def greet(): pass")
    lib.register(s)
    listed = lib.list_skills()
    assert any(x.name == "greet" for x in listed)
    assert lib.get("greet") is s


def test_list_skills_category_filter():
    lib = SkillLibrary()
    lib.create_from_code(name="a", description="", code=_GOOD_CODE, category="math")
    lib.create_from_code(name="b", description="", code=_GOOD_CODE, category="text")
    math_only = lib.list_skills(category="math")
    assert [x.name for x in math_only] == ["a"]


def test_list_skills_tenant_isolation():
    lib = SkillLibrary()
    lib.create_from_code(name="shared", description="", code=_GOOD_CODE, tenant_id="t1")
    lib.create_from_code(name="other", description="", code=_GOOD_CODE, tenant_id="t2")
    t1 = lib.list_skills(tenant_id="t1")
    assert [x.name for x in t1] == ["shared"]


def test_update_bumps_patch_version_and_preserves_history():
    lib, skill = _make_skill()
    updated = lib.update(name="add", code=_GOOD_CODE.replace("a + b", "a + b + 1"), bump="patch")
    assert updated.metadata["version"] == "0.0.1"
    assert updated.metadata["previous_version"] is None
    # history keeps both versions
    hist = lib.history("add")
    assert len(hist) == 2
    # a second minor bump
    lib.update(name="add", bump="minor")
    assert lib.get("add").metadata["version"] == "0.1.0"


def test_update_unknown_skill_raises():
    lib = SkillLibrary()
    with pytest.raises(SkillError):
        lib.update(name="ghost", code=_GOOD_CODE)


def test_remove():
    lib, _ = _make_skill()
    assert lib.remove("add") is True
    assert lib.get("add") is None
    assert lib.remove("add") is False


def test_load_from_disk_fallback():
    # SkillRegistry-backed lookup works even when not explicitly loaded.
    import tempfile
    import os

    d = tempfile.mkdtemp()
    with open(os.path.join(d, "skill.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: disk_skill\ndescription: from disk\n---\ndef disk_skill():\n    pass\n")
    reg = SkillRegistry([d])
    lib = SkillLibrary(registry=reg)
    lib.load_from_disk()
    assert lib.get("disk_skill") is not None
    assert any(x.name == "disk_skill" for x in lib.list_skills())


def test_verifier_passes_test_cases():
    lib, skill = _make_skill()
    verifier = SkillVerifier(library=lib)
    result = verifier.verify(
        skill,
        test_cases=[
            {"call": {"a": 1, "b": 2}, "expect": 3},
            {"call": {"a": 10, "b": -4}, "expect": 6},
        ],
    )
    assert isinstance(result, SkillVerificationResult)
    assert result.passed is True
    assert result.attempts == 2


def test_verifier_fails_on_wrong_expectation():
    lib, skill = _make_skill()
    verifier = SkillVerifier(library=lib)
    result = verifier.verify(skill, test_cases=[{"call": {"a": 1, "b": 1}, "expect": 99}])
    assert result.passed is False
    assert result.expected == 99
    assert result.got == 2


def test_verifier_syntax_error():
    # Build a Skill directly (create_from_code rejects bad syntax upfront, which
    # is the intended guard), so we can exercise the verifier's own check.
    lib = SkillLibrary()
    bad = Skill(name="bad", description="", content=_BAD_SYNTAX)
    lib.register(bad)
    verifier = SkillVerifier(library=lib)
    result = verifier.verify(bad, test_cases=[{"call": {}, "expect": 1}])
    assert result.passed is False
    assert "syntax" in (result.error or "").lower()


def test_verifier_by_name_unknown():
    verifier = SkillVerifier(library=SkillLibrary())
    with pytest.raises(SkillVerificationError):
        verifier.verify_by_name("nope", test_cases=[])
