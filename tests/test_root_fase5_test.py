"""Tests para el ROOT AGENT (ADK sub_agents) — Fase 5.

Cubre: enrutamiento a specialist correcto, manejo por root cuando el router
devuelve None, error cuando no hay root_handler, router con nombre inexistente,
registro duplicado de specialist, falta de router/root_handler en compile, y
persistencia de la decisión de enrutamiento vía RootCheckpointStore.

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). No se inventan fixtures.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from ciel.orchestration import (
    RootAgent,
    RootAgentError,
    RootCheckpointStore,
    RootRunner,
    RootState,
    Specialist,
)
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


def _simple_db_handler(state: RootState) -> str:
    return f"db-handled:{state.prompt}"


def _simple_net_handler(state: RootState) -> str:
    return f"net-handled:{state.prompt}"


# --------------------------------------------------------------------------- #
# 1. Root enruta a specialist correcto
# --------------------------------------------------------------------------- #
def test_root_routes_to_correct_specialist():
    db_calls = []
    net_calls = []

    def db_handler(state: RootState) -> str:
        db_calls.append(state.prompt)
        return f"db:{state.prompt}"

    def net_handler(state: RootState) -> str:
        net_calls.append(state.prompt)
        return f"net:{state.prompt}"

    def router(prompt: str):
        if "sql" in prompt.lower():
            return "db"
        if "http" in prompt.lower():
            return "net"
        return None

    agent = (
        RootAgent(name="root")
        .add_specialist(Specialist("db", db_handler, "base de datos"))
        .add_specialist(Specialist("net", net_handler, "red"))
        .set_router(router)
    )
    runner: RootRunner = agent.compile()

    st_sql = asyncio.run(runner.route("SELECT * FROM sql_users"))
    assert st_sql.route == "db"
    assert st_sql.result == "db:SELECT * FROM sql_users"
    assert not st_sql.handled_by_root
    assert db_calls == ["SELECT * FROM sql_users"]

    st_http = asyncio.run(runner.route("fetch http://example.com"))
    assert st_http.route == "net"
    assert st_http.result == "net:fetch http://example.com"
    assert not st_http.handled_by_root
    assert net_calls == ["fetch http://example.com"]


# --------------------------------------------------------------------------- #
# 2. Router devuelve None -> root_handler maneja
# --------------------------------------------------------------------------- #
def test_router_none_handled_by_root():
    root_calls = []

    def root_handler(state: RootState) -> str:
        root_calls.append(state.prompt)
        return f"root:{state.prompt}"

    def router(prompt: str):
        return None

    agent = (
        RootAgent(name="root")
        .add_specialist(Specialist("db", _simple_db_handler))
        .set_router(router)
        .set_root_handler(root_handler)
    )
    runner: RootRunner = agent.compile()

    state = asyncio.run(runner.route("algo generico sin especialista"))
    assert state.handled_by_root is True
    assert state.route is None
    assert state.result == "root:algo generico sin especialista"
    assert root_calls == ["algo generico sin especialista"]
    assert state.metadata["handled_by"] == "root"


# --------------------------------------------------------------------------- #
# 3. Router None y NO hay root_handler -> RootAgentError
# --------------------------------------------------------------------------- #
def test_router_none_without_root_handler_raises():
    def router(prompt: str):
        return None

    agent = (
        RootAgent(name="root")
        .add_specialist(Specialist("db", _simple_db_handler))
        .set_router(router)
        # sin set_root_handler
    )
    runner: RootRunner = agent.compile()

    with pytest.raises(RootAgentError) as excinfo:
        asyncio.run(runner.route("nadie maneja esto"))
    assert "root_handler" in str(excinfo.value).lower()


# --------------------------------------------------------------------------- #
# 4. Router devuelve nombre inexistente -> RootAgentError al route
# --------------------------------------------------------------------------- #
def test_router_unknown_specialist_raises():
    def router(prompt: str):
        return "ghost"

    agent = (
        RootAgent(name="root")
        .add_specialist(Specialist("db", _simple_db_handler))
        .set_router(router)
    )
    runner: RootRunner = agent.compile()

    with pytest.raises(RootAgentError) as excinfo:
        asyncio.run(runner.route("a donde va esto"))
    assert "ghost" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 5. add_specialist duplicado -> RootAgentError al registrar
# --------------------------------------------------------------------------- #
def test_duplicate_specialist_raises():
    agent = RootAgent(name="root")
    agent.add_specialist(Specialist("db", _simple_db_handler))

    with pytest.raises(RootAgentError) as excinfo:
        agent.add_specialist(Specialist("db", _simple_net_handler))
    assert "db" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 6. compile sin router ni root_handler -> RootAgentError en compile
# --------------------------------------------------------------------------- #
def test_compile_without_router_or_root_handler_raises():
    agent = RootAgent(name="root")
    agent.add_specialist(Specialist("db", _simple_db_handler))

    with pytest.raises(RootAgentError) as excinfo:
        agent.compile()
    assert "router" in str(excinfo.value).lower()


# --------------------------------------------------------------------------- #
# 7. Checkpointer: estado de enrutamiento persistido y recargado
# --------------------------------------------------------------------------- #
def test_root_checkpoint_store_persists_routed_state():
    store, path = _make_store()
    try:
        def router(prompt: str):
            return "db" if "sql" in prompt.lower() else None

        def db_handler(state: RootState) -> str:
            return f"db:{state.prompt}"

        agent = (
            RootAgent(name="root")
            .add_specialist(Specialist("db", db_handler))
            .set_router(router)
        )
        runner: RootRunner = agent.compile()

        run_id = "root-run-1"
        state = asyncio.run(runner.route("SELECT sql_count FROM t"))

        # Persistimos la decision de enrutamiento.
        checkpointer = RootCheckpointStore(store)
        checkpoint_id = checkpointer.save(
            run_id=run_id, state=state, tenant_id=None, session_id=None
        )
        assert isinstance(checkpoint_id, str) and checkpoint_id

        # Recargamos desde el almacenamiento y reconstruimos el RootState.
        loaded = checkpointer.load(run_id=run_id, tenant_id=None, session_id=None)
        assert loaded is not None
        assert loaded["state"]["route"] == "db"
        assert loaded["state"]["result"] == "db:SELECT sql_count FROM t"

        restored = RootState.from_snapshot(loaded["state"])
        assert restored.route == "db"
        assert restored.result == "db:SELECT sql_count FROM t"
        assert restored.metadata["handled_by"] == "db"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
