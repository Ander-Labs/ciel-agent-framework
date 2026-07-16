"""Fase 12 — Skill Composition Engine (Item 3).

Offline tests (no network, no API keys) covering ``SkillComposition.compose``:

* compose 2 skills with ``sequence`` produces code defining both source
  functions AND a composed function that chains them;
* the composed skill's metadata reflects the source skills and combinator;
* the composed skill is retrievable via ``SkillLibrary.get()``.
"""

from __future__ import annotations

from ciel.runtime.skills import Skill
from ciel.runtime.skills_lib import SkillLibrary
from ciel.runtime.skill_composition import SkillComposition, SkillCompositionError


# Two independent skills, each defining exactly one top-level function.
_SKILL_A = Skill(
    name="inc",
    description="increment by one",
    content="def inc(x):\n    \"\"\"Increment.\"\"\"\n    return x + 1\n",
    category="math",
)

_SKILL_B = Skill(
    name="double",
    description="multiply by two",
    content="def double(x):\n    \"\"\"Double.\"\"\"\n    return x * 2\n",
    category="math",
)


def test_compose_sequence_defines_both_functions_and_composed():
    composer = SkillComposition()
    composed = composer.compose("inc_then_double", [_SKILL_A, _SKILL_B], "sequence")

    content = composed.content
    # Both source functions are present in the fused body.
    assert "def inc(x):" in content
    assert "def double(x):" in content
    # The composed function is also defined.
    assert "def inc_then_double(" in content

    # The composed function wires the sources in order (sequence pipeline).
    # Running it should produce inc -> double: (3 + 1) * 2 == 8.
    namespace: dict = {}
    exec(composed.content, namespace)
    assert callable(namespace["inc_then_double"])
    assert namespace["inc_then_double"](3) == 8

    # Syntax is valid as a standalone module.
    compile(composed.content, "<composed>", "exec")


def test_compose_metadata_reflects_source_skills():
    composer = SkillComposition()
    composed = composer.compose("pipeline", [_SKILL_A, _SKILL_B], "sequence")

    assert composed.metadata["combinator"] == "sequence"
    assert composed.metadata["source_skills"] == ["inc", "double"]
    comp = composed.metadata["composition"]
    assert comp["combinator"] == "sequence"
    assert comp["source_skills"] == ["inc", "double"]
    assert comp["source_callables"] == {"inc": "inc", "double": "double"}


def test_compose_registers_into_library_get_returns_it():
    lib = SkillLibrary()
    composer = SkillComposition()
    composed = composer.compose(
        "inc_then_double", [_SKILL_A, _SKILL_B], "sequence", library=lib
    )

    # The composed skill is retrievable from the library.
    fetched = lib.get("inc_then_double")
    assert fetched is composed
    assert fetched.name == "inc_then_double"

    # And it appears in the listing by category.
    listed = lib.list_skills(category="math")
    assert any(s.name == "inc_then_double" for s in listed)


def test_compose_parallel_runs_all():
    composer = SkillComposition()
    composed = composer.compose("par", [_SKILL_A, _SKILL_B], "parallel")
    namespace: dict = {}
    exec(composed.content, namespace)
    # parallel: each source gets the same args, results gathered in a list.
    assert namespace["par"](3) == [4, 6]


def test_compose_selector_takes_first_success():
    failing = Skill(
        name="boom",
        description="always raises",
        content="def boom(x):\n    raise ValueError('nope')\n",
    )
    composer = SkillComposition()
    composed = composer.compose("sel", [failing, _SKILL_A], "selector")
    namespace: dict = {}
    exec(composed.content, namespace)
    # selector: first source raises, second succeeds.
    assert namespace["sel"](3) == 4


def test_compose_rejects_empty_sources():
    composer = SkillComposition()
    import pytest

    with pytest.raises(SkillCompositionError):
        composer.compose("x", [], "sequence")


def test_compose_rejects_unknown_combinator():
    composer = SkillComposition()
    import pytest

    with pytest.raises(SkillCompositionError):
        composer.compose("x", [_SKILL_A], "nonsense")
