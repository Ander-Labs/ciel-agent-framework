"""Tests offline de memoria episódica (Pilar A — Fase 17, v0.11.0).

Verifica el EpisodicStore sobre SqliteStateBackend: append, get_recent,
get_by_id, search filtrada por tenant, clear_session y aislamiento
cross-tenant. Sin red, sin embeddings.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ciel.runtime.memory_episodic import EpisodicStore, MemoryConfig
from ciel.runtime.state_backend import SqliteStateBackend


@pytest.fixture()
def backend():
    tmp = tempfile.mkdtemp(prefix="ciel-mem-")
    db = str(Path(tmp) / "state.sqlite")
    be = SqliteStateBackend(db)
    yield be
    be.close()


def test_append_and_get_recent(backend):
    store = EpisodicStore(backend)
    store.append(
        tenant_id="t1", session_id="s1", role="user", content="Hola"
    )
    store.append(
        tenant_id="t1", session_id="s1", role="assistant", content="Hola, ¿en qué ayudo?"
    )
    recent = store.get_recent(tenant_id="t1", session_id="s1", limit=8)
    assert len(recent) == 2
    # Orden cronológico ascendente.
    assert recent[0].role == "user"
    assert recent[1].role == "assistant"
    assert recent[1].content == "Hola, ¿en qué ayudo?"


def test_get_by_id(backend):
    store = EpisodicStore(backend)
    mem = store.append(
        tenant_id="t1", session_id="s1", role="user", content="record"
    )
    fetched = store.get_by_id(
        tenant_id="t1", session_id="s1", memory_id=mem.id
    )
    assert fetched is not None
    assert fetched.content == "record"
    assert fetched.tenant_id == "t1"


def test_search_is_filtered_by_tenant(backend):
    store = EpisodicStore(backend)
    store.append(tenant_id="t1", session_id="s1", role="user", content="contraseña segura")
    store.append(tenant_id="t2", session_id="sX", role="user", content="contraseña segura")
    hits_t1 = store.search(tenant_id="t1", query="contraseña", limit=5)
    hits_t2 = store.search(tenant_id="t2", query="contraseña", limit=5)
    # Cada tenant solo ve sus propios episodios (sin fuga cross-tenant).
    assert len(hits_t1) == 1 and hits_t1[0].tenant_id == "t1"
    assert len(hits_t2) == 1 and hits_t2[0].tenant_id == "t2"


def test_tenant_isolation_recent(backend):
    store = EpisodicStore(backend)
    store.append(tenant_id="t1", session_id="s1", role="user", content="A")
    store.append(tenant_id="t2", session_id="s1", role="user", content="B")
    only_t1 = store.get_recent(tenant_id="t1", session_id="s1", limit=8)
    assert [m.content for m in only_t1] == ["A"]


def test_clear_session(backend):
    store = EpisodicStore(backend)
    store.append(tenant_id="t1", session_id="s1", role="user", content="x")
    store.append(tenant_id="t1", session_id="s2", role="user", content="y")
    store.clear_session(tenant_id="t1", session_id="s1")
    assert store.get_recent(tenant_id="t1", session_id="s1", limit=8) == []
    assert len(store.get_recent(tenant_id="t1", session_id="s2", limit=8)) == 1


def test_as_context_serializes(backend):
    store = EpisodicStore(backend)
    store.append(tenant_id="t1", session_id="s1", role="user", content="Pregunta")
    store.append(tenant_id="t1", session_id="s1", role="assistant", content="Respuesta")
    ctx = store.as_context(tenant_id="t1", session_id="s1", recent=8)
    assert "[user] Pregunta" in ctx
    assert "[assistant] Respuesta" in ctx


def test_memory_config_disabled():
    cfg = MemoryConfig.disabled()
    assert cfg.enabled is False
    assert MemoryConfig().enabled is True
