"""Fase 14 / F15 — StateBackend compartido (multi-réplica).

Cubre:
* SqliteStateBackend (default offline) — superficie set/get/delete/search/
  record_tool_execution/close/is_ready.
* MemoryStore sigue siendo un StateBackend retrocompatible (MemoryStore(path)).
* build_state_backend resuelve backend por env (sqlite por defecto, postgres
  requiere DSN).
* PostgresStateBackend (SKIP si no hay CIEL_STATE_DSN; no requerido para CI).
* Interoperabilidad: los stores de resume aceptan un StateBackend.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ciel.runtime.memory import MemoryStore
from ciel.runtime.state_backend import (
    PostgresStateBackend,
    SqliteStateBackend,
    StateBackend,
    build_state_backend,
)


@pytest.fixture
def sqlite_backend(tmp_path: Path) -> SqliteStateBackend:
    return SqliteStateBackend(str(tmp_path / "state.sqlite"))


def test_sqlite_backend_set_get_delete(sqlite_backend: SqliteStateBackend) -> None:
    assert sqlite_backend.get(tenant_id="t1", session_id="s1", key="k") is None
    sqlite_backend.set(tenant_id="t1", session_id="s1", key="k", value={"a": 1})
    assert sqlite_backend.get(tenant_id="t1", session_id="s1", key="k") == {"a": 1}
    sqlite_backend.delete(tenant_id="t1", session_id="s1", key="k")
    assert sqlite_backend.get(tenant_id="t1", session_id="s1", key="k") is None


def test_sqlite_backend_tenant_isolation(sqlite_backend: SqliteStateBackend) -> None:
    sqlite_backend.set(tenant_id="t1", session_id="s1", key="k", value="v1")
    sqlite_backend.set(tenant_id="t2", session_id="s1", key="k", value="v2")
    sqlite_backend.set(tenant_id=None, session_id="s1", key="k", value="v3")
    assert sqlite_backend.get(tenant_id="t1", session_id="s1", key="k") == "v1"
    assert sqlite_backend.get(tenant_id="t2", session_id="s1", key="k") == "v2"
    assert sqlite_backend.get(tenant_id=None, session_id="s1", key="k") == "v3"


def test_sqlite_backend_upsert_idempotente(sqlite_backend: SqliteStateBackend) -> None:
    # Simula dos réplicas escribiendo la misma clave (race-safe).
    sqlite_backend.set(tenant_id="t1", session_id="s1", key="k", value="first")
    sqlite_backend.set(tenant_id="t1", session_id="s1", key="k", value="second")
    assert sqlite_backend.get(tenant_id="t1", session_id="s1", key="k") == "second"


def test_sqlite_backend_record_tool_execution(sqlite_backend: SqliteStateBackend) -> None:
    sqlite_backend.record_tool_execution(
        tenant_id="t1",
        session_id="s1",
        toolset="default",
        tool_name="echo",
        arguments={"x": 1},
        started_at="2026-07-17T00:00:00+00:00",
        finished_at="2026-07-17T00:00:01+00:00",
        duration_ms=1000,
        output="ok",
    )
    # No debe lanzar; el log se persiste en tool_execution_log.
    sqlite_backend.close()


def test_sqlite_backend_is_ready(sqlite_backend: SqliteStateBackend) -> None:
    assert sqlite_backend.is_ready() is True


def test_memory_store_is_state_backend(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "legacy.sqlite"))
    assert isinstance(store, StateBackend)
    store.set(tenant_id="t1", session_id="s1", key="k", value={"x": 9})
    assert store.get(tenant_id="t1", session_id="s1", key="k") == {"x": 9}
    store.close()


def test_build_state_backend_default_sqlite(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CIEL_STATE_BACKEND", raising=False)
    monkeypatch.delenv("CIEL_STATE_DSN", raising=False)
    monkeypatch.setenv("CIEL_STATE_SQLITE", str(tmp_path / "def.sqlite"))
    backend = build_state_backend()
    assert isinstance(backend, SqliteStateBackend)
    assert backend.backend_type == "sqlite"
    backend.close()


def test_build_state_backend_postgres_requires_dsn(monkeypatch) -> None:
    monkeypatch.setenv("CIEL_STATE_BACKEND", "postgres")
    monkeypatch.delenv("CIEL_STATE_DSN", raising=False)
    with pytest.raises(RuntimeError):
        build_state_backend()


def test_build_state_backend_postgres_with_dsn(monkeypatch) -> None:
    dsn = os.getenv("CIEL_STATE_DSN")
    if not dsn:
        pytest.skip("CIEL_STATE_DSN no configurado (Postgres opt-in)")
    monkeypatch.setenv("CIEL_STATE_BACKEND", "postgres")
    monkeypatch.setenv("CIEL_STATE_DSN", dsn)
    backend = build_state_backend()
    assert isinstance(backend, PostgresStateBackend)
    assert backend.backend_type == "postgres"
    backend.close()


def test_resume_stores_accept_state_backend(sqlite_backend: SqliteStateBackend) -> None:
    # Los 4 stores de resume deben aceptar cualquier StateBackend.
    from ciel.orchestration.agent import EventLoopCheckpointStore
    from ciel.orchestration.graph import GraphCheckpointStore
    from ciel.orchestration.session import SessionStore
    from ciel.runtime.checkpoints import CheckpointStore

    CheckpointStore(sqlite_backend)
    SessionStore(sqlite_backend)
    GraphCheckpointStore(sqlite_backend)
    EventLoopCheckpointStore(sqlite_backend)
