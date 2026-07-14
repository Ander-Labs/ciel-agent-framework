"""Tests para RootRunner + SessionStore entre turnos (Fase 5).

Verifica que ``RootRunner.route`` mantiene el session state persistente entre
turnos usando ``SessionStore`` sobre ``MemoryStore`` (SQLite real), estilo ADK
session state durable por tenant, OFFLINE-SAFE (sin red ni proveedor).

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina ``route`` con ``asyncio.run`` (sin pytest-asyncio). No se inventan
fixtures.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from ciel.orchestration import RootAgent, RootRunner, RootState, Specialist
from ciel.orchestration.session import SessionStore
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un SessionStore real (sobre MemoryStore SQLite temporal).

    Devuelve (store, mem, path) donde ``store`` es el ``SessionStore`` que se
    pasa a ``route`` y ``mem`` es el ``MemoryStore`` subyacente (para liberar
    el lock de SQLite en Windows antes de ``os.remove``).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    mem = MemoryStore(path)
    return SessionStore(mem), mem, path


def _close_and_remove(path: str, mem: MemoryStore) -> None:
    """Libera el lock de SQLite en Windows antes de borrar el archivo."""
    try:
        mem.conn.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _db_handler(state: RootState) -> str:
    return f"db:{state.prompt}"


def _root_handler(state: RootState) -> str:
    return f"root:{state.prompt}"


# --------------------------------------------------------------------------- #
# 1. Dos route() consecutivos con MISMO session_id + SessionStore + tenant_id
# --------------------------------------------------------------------------- #
def test_session_state_persists_across_two_turns():
    store, mem, path = _make_store()
    try:
        agent = (
            RootAgent(name="root")
            .add_specialist(Specialist("db", _db_handler))
            .set_router(lambda p: "db")
        )
        runner: RootRunner = agent.compile()
        sid = "sess-persist"
        tid = "tenant-A"

        st1 = asyncio.run(
            runner.route("turno uno", session_id=sid, session_store=store, tenant_id=tid)
        )
        assert st1.route == "db"
        # El primer turno no tiene historial previo.
        assert st1.history == []

        st2 = asyncio.run(
            runner.route("turno dos", session_id=sid, session_store=store, tenant_id=tid)
        )
        # El 2do RootState.history tiene 1 turno previo (el del 1er turno).
        assert len(st2.history) == 1
        assert st2.history[0]["route"] == "db"
        assert st2.history[0]["prompt"] == "turno uno"
        # El turno actual NO se incluye en history (solo los previos).
        assert st2.prompt == "turno dos"
    finally:
        _close_and_remove(path, mem)


# --------------------------------------------------------------------------- #
# 2. Un 3er turno por root_handler (router devuelve None) también se acumula
# --------------------------------------------------------------------------- #
def test_root_handler_turn_accumulates_in_history():
    store, mem, path = _make_store()
    try:
        def router(prompt: str):
            # El primer turno va al specialist; el siguiente lo maneja root.
            return "db" if "db" in prompt.lower() else None

        agent = (
            RootAgent(name="root")
            .add_specialist(Specialist("db", _db_handler))
            .set_router(router)
            .set_root_handler(_root_handler)
        )
        runner: RootRunner = agent.compile()
        sid = "sess-root"
        tid = "tenant-B"

        st1 = asyncio.run(
            runner.route("consulta db", session_id=sid, session_store=store, tenant_id=tid)
        )
        assert st1.route == "db"
        assert not st1.handled_by_root

        st2 = asyncio.run(
            runner.route("consulta generica", session_id=sid, session_store=store, tenant_id=tid)
        )
        # El turno de root se acumula y marca handled_by_root.
        assert st2.handled_by_root is True
        assert st2.route is None
        # El historial de la session crece a 2 turnos (specialist + root).
        hist = store.history(tenant_id=tid, session_id=sid)
        assert len(hist) == 2
        assert hist[0]["route"] == "db"
        assert hist[0]["handled_by_root"] is False
        assert hist[1]["route"] is None
        assert hist[1]["handled_by_root"] is True
    finally:
        _close_and_remove(path, mem)


# --------------------------------------------------------------------------- #
# 3. Session state sobrevive a un NUEVO RootRunner (mismo agent.compile())
# --------------------------------------------------------------------------- #
def test_session_survives_new_runner_offline_safe():
    """3 turnos con un runner; un NUEVO runner lee store.history() -> 3 turnos."""

    def build_agent() -> RootAgent:
        return (
            RootAgent(name="root")
            .add_specialist(Specialist("db", _db_handler))
            .set_router(lambda p: "db")
        )

    store, mem, path = _make_store()
    try:
        runner1: RootRunner = build_agent().compile()
        sid = "sess-survive"
        tid = "tenant-C"

        asyncio.run(runner1.route("t1", session_id=sid, session_store=store, tenant_id=tid))
        asyncio.run(runner1.route("t2", session_id=sid, session_store=store, tenant_id=tid))
        asyncio.run(runner1.route("t3", session_id=sid, session_store=store, tenant_id=tid))

        # NUEVO runner (misma definición de agente) lee directamente el store.
        runner2: RootRunner = build_agent().compile()
        hist = store.history(tenant_id=tid, session_id=sid)
        assert len(hist) == 3
        assert [h["prompt"] for h in hist] == ["t1", "t2", "t3"]

        # Y el nuevo runner rehidrata el historial al routear un 4to turno.
        st4 = asyncio.run(
            runner2.route("t4", session_id=sid, session_store=store, tenant_id=tid)
        )
        assert st4.route == "db"
        assert len(st4.history) == 3
        assert [h["prompt"] for h in st4.history] == ["t1", "t2", "t3"]
    finally:
        _close_and_remove(path, mem)


# --------------------------------------------------------------------------- #
# 4. SessionStore.list_sessions(tenant_id) incluye el session_id usado
# --------------------------------------------------------------------------- #
def test_list_sessions_includes_used_session():
    store, mem, path = _make_store()
    try:
        agent = (
            RootAgent(name="root")
            .add_specialist(Specialist("db", _db_handler))
            .set_router(lambda p: "db")
        )
        runner: RootRunner = agent.compile()
        sid = "sess-list"
        tid = "tenant-D"

        asyncio.run(
            runner.route("x", session_id=sid, session_store=store, tenant_id=tid)
        )
        sessions = store.list_sessions(tenant_id=tid)
        assert isinstance(sessions, list)
        assert sid in sessions
    finally:
        _close_and_remove(path, mem)


# --------------------------------------------------------------------------- #
# 5. Aislamiento por tenant: session_id compartido, tenants distintos
# --------------------------------------------------------------------------- #
def test_tenant_isolation_same_session_id():
    store, mem, path = _make_store()
    try:
        agent = (
            RootAgent(name="root")
            .add_specialist(Specialist("db", _db_handler))
            .set_router(lambda p: "db")
        )
        runner: RootRunner = agent.compile()
        sid = "sess-shared"

        asyncio.run(
            runner.route("turno t1", session_id=sid, session_store=store, tenant_id="t1")
        )
        asyncio.run(
            runner.route("turno t2", session_id=sid, session_store=store, tenant_id="t2")
        )

        h1 = store.history(tenant_id="t1", session_id=sid)
        h2 = store.history(tenant_id="t2", session_id=sid)

        # Cada tenant mantiene su propio historial: no se mezclan.
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0]["prompt"] == "turno t1"
        assert h2[0]["prompt"] == "turno t2"

        # Y los índices de session también están aislados por tenant.
        assert sid in store.list_sessions(tenant_id="t1")
        assert sid in store.list_sessions(tenant_id="t2")
    finally:
        _close_and_remove(path, mem)
