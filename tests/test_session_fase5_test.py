"""Tests para SessionStore (session state persistente por tenant) — Fase 5.

Cubre: append_turn/history, acumulación y orden de turnos, multitenancy
(tenant_id=None normalizado a "__none__"), save_state/load_state con default,
link_board_task/board_links sin duplicados e integración con board, y
list_sessions por tenant.

Patrón del proyecto: funciones ``def test_*`` síncronas (SessionStore es
síncrono, sin corutinas). No se inventan fixtures. Se usa un MemoryStore
SQLite temporal real y se libera el lock en Windows con ``store.close()``.
"""

from __future__ import annotations

import os
import tempfile

from ciel.orchestration.session import SessionStore
from ciel.runtime.memory import MemoryStore


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


def _make_session(store):
    """Devuelve el SessionStore sobre el MemoryStore ya abierto."""
    return SessionStore(store)


# --------------------------------------------------------------------------- #
# 1. append_turn + history: un turno persiste y se recupera
# --------------------------------------------------------------------------- #
def test_append_turn_and_history_persists_single_turn():
    store, path = _make_store()
    try:
        session = _make_session(store)
        turn = {"role": "user", "content": "hola"}
        session.append_turn(tenant_id="t1", session_id="s1", turn=turn)

        hist = session.history(tenant_id="t1", session_id="s1")
        assert isinstance(hist, list), "history debe devolver una lista"
        assert len(hist) == 1, f"esperaba 1 turno, obtuve {len(hist)}"
        assert hist[0]["content"] == "hola", "el contenido del turno debe persistir"
        assert hist[0]["role"] == "user"
        # append_turn inyecta un timestamp por defecto.
        assert "ts" in hist[0], "append_turn debe añadir un ts por defecto"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 2. Múltiples turnos se acumulan en orden
# --------------------------------------------------------------------------- #
def test_multiple_turns_accumulate_in_order():
    store, path = _make_store()
    try:
        session = _make_session(store)
        for i in range(3):
            session.append_turn(
                tenant_id="t1", session_id="s1", turn={"role": "user", "content": f"m{i}"}
            )

        hist = session.history(tenant_id="t1", session_id="s1")
        assert len(hist) == 3, f"esperaba 3 turnos, obtuve {len(hist)}"
        contents = [t["content"] for t in hist]
        assert contents == ["m0", "m1", "m2"], f"orden incorrecto: {contents}"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 3. Multitenancy: tenant_id=None y tenant_id='t1' NO colisionan
# --------------------------------------------------------------------------- #
def test_multitenancy_isolation_none_vs_t1():
    store, path = _make_store()
    try:
        session = _make_session(store)
        # Mismo session_id, distinto tenant -> deben aislarse.
        session.append_turn(
            tenant_id=None, session_id="same", turn={"role": "user", "content": "anon"}
        )
        session.append_turn(
            tenant_id="t1", session_id="same", turn={"role": "user", "content": "tenant"}
        )

        none_hist = session.history(tenant_id=None, session_id="same")
        t1_hist = session.history(tenant_id="t1", session_id="same")

        assert len(none_hist) == 1, f"None debe tener 1 turno, obtuve {len(none_hist)}"
        assert len(t1_hist) == 1, f"t1 debe tener 1 turno, obtuve {len(t1_hist)}"
        assert none_hist[0]["content"] == "anon"
        assert t1_hist[0]["content"] == "tenant"
        assert none_hist[0]["content"] != t1_hist[0]["content"], (
            "los turnos de distinto tenant no deben colisionar"
        )
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 4. save_state/load_state round-trip con default cuando no existe
# --------------------------------------------------------------------------- #
def test_save_load_state_roundtrip_and_default():
    store, path = _make_store()
    try:
        session = _make_session(store)

        # Clave inexistente -> default.
        missing = session.load_state(
            tenant_id="t1", session_id="s1", key="nope", default="fallback"
        )
        assert missing == "fallback", f"esperaba fallback, obtuve {missing!r}"

        # Round-trip.
        session.save_state(tenant_id="t1", session_id="s1", key="k", value={"a": 1})
        loaded = session.load_state(tenant_id="t1", session_id="s1", key="k")
        assert loaded == {"a": 1}, f"round-trip falló: {loaded!r}"

        # Multitenancy también aísla el state.
        other = session.load_state(tenant_id="t2", session_id="s1", key="k", default=None)
        assert other is None, "el state no debe filtrarse entre tenants"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 5. link_board_task + board_links sin duplicados (integrado a board+session)
# --------------------------------------------------------------------------- #
def test_link_board_task_no_duplicates_and_board_links():
    store, path = _make_store()
    try:
        session = _make_session(store)
        # Vincular dos tareas distintas.
        session.link_board_task(tenant_id="t1", session_id="s1", board_task_id="B-1")
        session.link_board_task(tenant_id="t1", session_id="s1", board_task_id="B-2")
        # Vincular B-1 de nuevo -> no debe duplicarse.
        session.link_board_task(tenant_id="t1", session_id="s1", board_task_id="B-1")

        links = session.board_links(tenant_id="t1", session_id="s1")
        assert links == ["B-1", "B-2"], f"links inesperados: {links}"
        assert len(links) == 2, "no debe haber duplicados en board_links"

        # Integración board+session: el link persiste y se aisla por tenant.
        other = session.board_links(tenant_id="t2", session_id="s1")
        assert other == [], "board_links no debe filtrarse entre tenants"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 6. list_sessions: tras append_turn con tenant_id, lista el session_id
# --------------------------------------------------------------------------- #
def test_list_sessions_registers_after_append_turn():
    store, path = _make_store()
    try:
        session = _make_session(store)
        # Sin turnos todavía -> la session no está registrada.
        assert session.list_sessions(tenant_id="t1") == [], (
            "no debe haber sessions antes de append_turn"
        )

        session.append_turn(
            tenant_id="t1", session_id="s1", turn={"role": "user", "content": "x"}
        )

        listed = session.list_sessions(tenant_id="t1")
        assert "s1" in listed, f"s1 debería estar registrado, obtuve {listed}"
        assert len(listed) == 1, f"esperaba 1 session, obtuve {listed}"

        # También se registra vía save_state.
        session.save_state(tenant_id="t1", session_id="s2", key="k", value=1)
        listed2 = session.list_sessions(tenant_id="t1")
        assert set(listed2) == {"s1", "s2"}, f"esperaba {{s1,s2}}, obtuve {listed2}"

        # El índice se aisla por tenant.
        assert session.list_sessions(tenant_id="t2") == [], (
            "list_sessions no debe cruzar tenants"
        )
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass
