"""Fase 12 — Skill Versioning + changelog + evolution tree (Item 2). Offline.

Network-free, API-key-free tests covering the helpers in
``ciel.runtime.skill_versioning``. They operate on a passed ``SkillLibrary`` and
must not touch ``skills_lib.py`` or the low-level ``Skill``/``SkillRegistry``.
"""

from __future__ import annotations

import pytest

from ciel.runtime.skill_versioning import (
    INITIAL_VERSION,
    SkillVersion,
    changelog,
    evolution_tree,
    set_changelog,
)
from ciel.runtime.skills_lib import SkillError, SkillLibrary

_GOOD_CODE = (
    "def add(a, b):\n"
    "    \"\"\"Sum two numbers.\"\"\"\n"
    "    return a + b\n"
)


def _lib_with_versions() -> SkillLibrary:
    """Create a lib with add@0.0.0 and two bumps (patch then minor)."""
    lib = SkillLibrary()
    lib.create_from_code(name="add", description="sum", code=_GOOD_CODE)
    # first update -> 0.0.1 (previous_version None because initial has no version)
    lib.update(name="add", code=_GOOD_CODE.replace("a + b", "a + b + 1"), bump="patch")
    # second update -> 0.1.0
    lib.update(name="add", code=_GOOD_CODE.replace("a + b", "a + b + 2"), bump="minor")
    return lib


# --- SkillVersion dataclass ------------------------------------------------


def test_skill_version_string_and_parse():
    v = SkillVersion(1, 2, 3)
    assert v.version == "1.2.3"
    assert SkillVersion.parse("2.5.0") == SkillVersion(2, 5, 0)


def test_skill_version_bump():
    base = SkillVersion(1, 2, 3)
    assert base.bump("patch") == SkillVersion(1, 2, 4)
    assert base.bump("minor") == SkillVersion(1, 3, 0)
    assert base.bump("major") == SkillVersion(2, 0, 0)


def test_skill_version_parse_invalid_raises():
    with pytest.raises(SkillError):
        SkillVersion.parse("not.a.version")


# --- set_changelog / changelog by version ----------------------------------


def test_set_and_get_changelog_initial_version():
    lib = SkillLibrary()
    lib.create_from_code(name="add", description="sum", code=_GOOD_CODE)
    sv = set_changelog(lib, "add", INITIAL_VERSION, "initial release")
    assert isinstance(sv, SkillVersion)
    assert sv.changelog == "initial release"
    assert sv.released_at is not None
    cl = changelog(lib, "add")
    assert cl[INITIAL_VERSION] == "initial release"


def test_set_changelog_after_bumps_keyed_by_version():
    lib = _lib_with_versions()
    set_changelog(lib, "add", "0.0.1", "fix off-by-one")
    set_changelog(lib, "add", "0.1.0", "configurable delta")
    cl = changelog(lib, "add")
    # every version present, keyed by its semver
    assert cl["0.0.0"] == ""
    assert cl["0.0.1"] == "fix off-by-one"
    assert cl["0.1.0"] == "configurable delta"
    # the changelog text is persisted on the right skill object in the library
    by_ver = {s.metadata.get("version") or INITIAL_VERSION: s for s in lib.history("add")}
    assert by_ver["0.0.1"].metadata["changelog"] == "fix off-by-one"
    assert by_ver["0.1.0"].metadata["changelog"] == "configurable delta"


def test_set_changelog_unknown_version_raises():
    lib = _lib_with_versions()
    with pytest.raises(SkillError):
        set_changelog(lib, "add", "9.9.9", "nope")


def test_set_changelog_unknown_skill_raises():
    with pytest.raises(SkillError):
        set_changelog(SkillLibrary(), "ghost", "0.0.0", "x")


def test_set_changelog_rejects_empty_text():
    lib = SkillLibrary()
    lib.create_from_code(name="add", description="sum", code=_GOOD_CODE)
    with pytest.raises(SkillError):
        set_changelog(lib, "add", INITIAL_VERSION, "")


# --- history preserves lineage after update() with bump --------------------


def test_history_preserves_lineage_after_bumps():
    lib = _lib_with_versions()
    hist = lib.history("add")
    assert len(hist) == 3
    # initial skill carries no explicit version
    assert hist[0].metadata.get("version") is None
    # first update is recorded as 0.0.1 with previous_version None (initial quirk)
    assert hist[1].metadata["version"] == "0.0.1"
    assert hist[1].metadata["previous_version"] is None
    # second update records its parent correctly
    assert hist[2].metadata["version"] == "0.1.0"
    assert hist[2].metadata["previous_version"] == "0.0.1"
    # get() returns the latest version
    assert lib.get("add").metadata["version"] == "0.1.0"


# --- evolution_tree reflects parents ---------------------------------------


def test_evolution_tree_reflects_parents():
    lib = _lib_with_versions()
    set_changelog(lib, "add", "0.0.0", "initial")
    set_changelog(lib, "add", "0.0.1", "fix")
    set_changelog(lib, "add", "0.1.0", "feature")
    tree = evolution_tree(lib, "add")
    assert tree["name"] == "add"
    assert tree["root"] == "0.0.0"
    assert tree["lineage"] == ["0.0.0", "0.0.1", "0.1.0"]
    nodes = tree["nodes"]
    assert set(nodes) == {"0.0.0", "0.0.1", "0.1.0"}
    # parent links (normalised so the first-update quirk is chained)
    assert nodes["0.0.0"]["parent"] is None
    assert nodes["0.0.1"]["parent"] == "0.0.0"
    assert nodes["0.1.0"]["parent"] == "0.0.1"
    # children lists
    assert nodes["0.0.0"]["children"] == ["0.0.1"]
    assert nodes["0.0.1"]["children"] == ["0.1.0"]
    assert nodes["0.1.0"]["children"] == []
    # changelog flows into the tree
    assert nodes["0.0.1"]["changelog"] == "fix"
    # raw previous_version is preserved for fidelity
    assert nodes["0.1.0"]["previous_version"] == "0.0.1"
    # sha256 preserved
    assert nodes["0.1.0"]["sha256"] == lib.get("add").sha256


def test_evolution_tree_unknown_skill_raises():
    with pytest.raises(SkillError):
        evolution_tree(SkillLibrary(), "ghost")


def test_evolution_tree_single_version():
    lib = SkillLibrary()
    lib.create_from_code(name="add", description="sum", code=_GOOD_CODE)
    set_changelog(lib, "add", INITIAL_VERSION, "only")
    tree = evolution_tree(lib, "add")
    assert tree["root"] == "0.0.0"
    assert tree["lineage"] == ["0.0.0"]
    assert tree["nodes"]["0.0.0"]["parent"] is None
    assert tree["nodes"]["0.0.0"]["children"] == []
