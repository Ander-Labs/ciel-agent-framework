"""Test de prompt evolution versionado (Fase 19, v0.13.0).

Verifica bump semver, evolution_tree y persistencia SQLite (tmp) con
aislamiento por tenant. OFFLINE.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ciel.runtime.prompt_versioning import (
    INITIAL_VERSION,
    PromptRegistry,
    PromptVersion,
    PromptVersioningError,
    sha256_text,
)
from ciel.runtime.state_backend import SqliteStateBackend


@pytest.fixture()
def backend():
    tmp = tempfile.mkdtemp(prefix="ciel-prompt-")
    db = str(Path(tmp) / "state.sqlite")
    be = SqliteStateBackend(db)
    yield be
    be.close()


@pytest.fixture()
def registry(backend):
    return PromptRegistry(backend)


# --- PromptVersion ----------------------------------------------------------


def test_version_string_and_parse():
    v = PromptVersion(1, 2, 3)
    assert v.version == "1.2.3"
    assert PromptVersion.parse("2.5.0") == PromptVersion(2, 5, 0)


def test_version_bump():
    base = PromptVersion(1, 2, 3)
    assert base.bump("patch") == PromptVersion(1, 2, 4)
    assert base.bump("minor") == PromptVersion(1, 3, 0)
    assert base.bump("major") == PromptVersion(2, 0, 0)


def test_version_parse_invalid_raises():
    with pytest.raises(PromptVersioningError):
        PromptVersion.parse("not.a.version")


def test_sha256_deterministic():
    a = sha256_text("hola")
    b = sha256_text("hola")
    c = sha256_text("hola ")
    assert a == b
    assert a != c


# --- PromptRegistry: create / update / get ----------------------------------


def test_create_initial_version(registry):
    pv = registry.create("greeter", "Eres un asistente.", tenant_id="t1", changelog="init")
    assert pv.version == INITIAL_VERSION
    assert pv.previous_version is None
    assert pv.sha256 == sha256_text("Eres un asistente.")
    got = registry.get("greeter", tenant_id="t1")
    assert got is not None
    assert got.prompt_text == "Eres un asistente."


def test_create_duplicate_raises(registry):
    registry.create("greeter", "v1", tenant_id="t1")
    with pytest.raises(PromptVersioningError):
        registry.create("greeter", "v2", tenant_id="t1")


def test_update_bumps_and_links(registry):
    registry.create("greeter", "v1", tenant_id="t1")
    pv = registry.update("greeter", "v2", tenant_id="t1", bump="minor", changelog="mejora")
    assert pv.version == "0.1.0"
    assert pv.previous_version == INITIAL_VERSION
    # get() sin version devuelve la última
    latest = registry.get("greeter", tenant_id="t1")
    assert latest.version == "0.1.0"
    # get() por version específica
    first = registry.get("greeter", tenant_id="t1", version=INITIAL_VERSION)
    assert first.prompt_text == "v1"


def test_update_unknown_raises(registry):
    with pytest.raises(PromptVersioningError):
        registry.update("ghost", "x", tenant_id="t1")


# --- history / evolution_tree ----------------------------------------------


def test_history_ordered(registry):
    registry.create("greeter", "v0", tenant_id="t1")
    registry.update("greeter", "v1", tenant_id="t1", bump="patch")
    registry.update("greeter", "v2", tenant_id="t1", bump="minor")
    hist = registry.history("greeter", tenant_id="t1")
    assert [h.version for h in hist] == ["0.0.0", "0.0.1", "0.1.0"]


def test_evolution_tree_reflects_parents(registry):
    registry.create("greeter", "v0", tenant_id="t1", changelog="init")
    registry.update("greeter", "v1", tenant_id="t1", bump="patch", changelog="fix")
    registry.update("greeter", "v2", tenant_id="t1", bump="minor", changelog="feat")
    tree = registry.evolution_tree("greeter", tenant_id="t1")
    assert tree["name"] == "greeter"
    assert tree["root"] == "0.0.0"
    assert tree["lineage"] == ["0.0.0", "0.0.1", "0.1.0"]
    nodes = tree["nodes"]
    assert nodes["0.0.0"]["parent"] is None
    assert nodes["0.0.1"]["parent"] == "0.0.0"
    assert nodes["0.1.0"]["parent"] == "0.0.1"
    assert nodes["0.0.1"]["changelog"] == "fix"
    assert nodes["0.1.0"]["changelog"] == "feat"


def test_evolution_tree_unknown_raises(registry):
    with pytest.raises(PromptVersioningError):
        registry.evolution_tree("ghost", tenant_id="t1")


# --- aislamiento por tenant -------------------------------------------------


def test_tenant_isolation(registry):
    registry.create("greeter", "prompt A", tenant_id="tenantA")
    registry.create("greeter", "prompt B", tenant_id="tenantB")
    a = registry.get("greeter", tenant_id="tenantA")
    b = registry.get("greeter", tenant_id="tenantB")
    assert a.prompt_text == "prompt A"
    assert b.prompt_text == "prompt B"
    # un tenant no ve el prompt del otro
    assert registry.get("greeter", tenant_id="tenantA") is not None
    assert registry.get("greeter", tenant_id="other") is None


# --- persistencia real (sobrevive a nueva instancia) -----------------------


def test_persists_across_instances():
    tmp = tempfile.mkdtemp(prefix="ciel-prompt-persist-")
    db = str(Path(tmp) / "state.sqlite")
    be1 = SqliteStateBackend(db)
    PromptRegistry(be1).create("p", "texto", tenant_id="t1")
    be1.close()
    be2 = SqliteStateBackend(db)
    got = PromptRegistry(be2).get("p", tenant_id="t1")
    be2.close()
    assert got is not None
    assert got.prompt_text == "texto"
