"""Tests formales de la Fase 8: HIL en grafo y observabilidad OTel.

Cubre el Human-in-the-loop (HIL) del StateGraph (pausa/approve/deny/resume
con RBAC) y la observabilidad OpenTelemetry (init_tracing in-memory,
span_count y OtlpAuditExporter).

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). OFFLINE-SAFE.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict

import pytest

from ciel.orchestration.graph import (
    GraphApprovalDenied,
    GraphCheckpointStore,
    GraphPaused,
    StateGraph,
)
from ciel.runtime.memory import MemoryStore
from ciel.enterprise.rbac import RBACEngine, RBACError
from ciel.observability.otel import (
    OTEL_AVAILABLE,
    OtlpAuditExporter,
    current_tracer,
    init_tracing,
    span_count,
)
from ciel.observability import AuditEvent


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_store():
    """Crea un MemoryStore SQLite temporal real y devuelve (store, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return MemoryStore(path), path


def _build_hil_graph():
    """Grafo entry -> a (require_approval) -> b -> finish.

    El nodo 'a' exige aprobación ('approve:deploy'); 'b' es un nodo normal
    que marca que el grafo continuó tras la aprobación.
    """

    def a(state_data: Dict[str, Any]) -> str:
        state_data["a_ran"] = True
        return "out-a"

    def b(state_data: Dict[str, Any]) -> str:
        state_data["b_ran"] = True
        return "out-b"

    def finish(state_data: Dict[str, Any]) -> str:
        state_data["finish_ran"] = True
        return "out-finish"

    g = StateGraph(name="hil")
    g.add_node("a", a, require_approval="approve:deploy")
    g.add_node("b", b)
    g.add_node("finish", finish)
    g.add_edge("a", "b")
    g.add_edge("b", "finish")
    g.set_entry_point("a")
    g.set_finish_point("finish")
    return g


def _make_rbac():
    rbac = RBACEngine()
    rbac.assign("alice", "admin", tenant_id="t1")
    rbac.assign("bob", "viewer", tenant_id="t1")
    return rbac


# --------------------------------------------------------------------------- #
# (a) Grafo pausa en nodo require_approval y lanza GraphPaused con node_id/action
# --------------------------------------------------------------------------- #
def test_hil_run_pauses_on_require_approval_with_correct_node_and_action():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        g = _build_hil_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1")

        with pytest.raises(GraphPaused) as excinfo:
            asyncio.run(runner.run(run_id="run-a"))

        exc = excinfo.value
        assert exc.node_id == "a"
        assert exc.action == "approve:deploy"
        assert exc.run_id == "run-a"

        # El checkpointer debe haber persistido paused=True en el nodo 'a'.
        ckpt = checkpointer.load(run_id="run-a", tenant_id="t1", session_id=None)
        assert ckpt is not None
        assert ckpt["paused"] is True
        assert ckpt["paused_node"] == "a"
        # El nodo pausado NO se ejecutó todavía.
        assert "a_ran" not in ckpt["state"]["data"]
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# (b) deny lanza GraphApprovalDenied y persiste paused=False
# --------------------------------------------------------------------------- #
def test_hil_deny_raises_and_persists_paused_false():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        g = _build_hil_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1")

        # Pausamos primero.
        with pytest.raises(GraphPaused):
            asyncio.run(runner.run(run_id="run-b"))

        # deny lanza GraphApprovalDenied.
        with pytest.raises(GraphApprovalDenied):
            asyncio.run(runner.deny("run-b", reason="no go"))

        # El checkpoint queda marcado como no pausado (no reanudable).
        ckpt = checkpointer.load(run_id="run-b", tenant_id="t1", session_id=None)
        assert ckpt is not None
        assert ckpt["paused"] is False
        assert ckpt["paused_node"] is None
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# (c) viewer sin permiso bloqueado por RBACError en approve
# --------------------------------------------------------------------------- #
def test_hil_approve_with_unprivileged_viewer_raises_rbac_error():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        rbac = _make_rbac()
        g = _build_hil_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1")

        with pytest.raises(GraphPaused):
            asyncio.run(runner.run(run_id="run-c"))

        # bob es 'viewer' (sin approve:*) => RBACError.
        with pytest.raises(RBACError):
            asyncio.run(
                runner.approve("run-c", approver="bob", rbac=rbac)
            )

        # Tras el rechazo RBAC, el grafo sigue pausado (no avanzó).
        ckpt = checkpointer.load(run_id="run-c", tenant_id="t1", session_id=None)
        assert ckpt["paused"] is True
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# (d) admin aprueba y grafo completa con nodo ejecutado
# --------------------------------------------------------------------------- #
def test_hil_admin_approve_completes_graph_with_node_executed():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        rbac = _make_rbac()
        g = _build_hil_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1")

        with pytest.raises(GraphPaused):
            asyncio.run(runner.run(run_id="run-d"))

        # alice es 'admin' (incluye approve:*) => aprueba y continúa.
        state = asyncio.run(runner.approve("run-d", approver="alice", rbac=rbac))

        # El nodo pausado 'a' se ejecutó y el grafo completó hasta finish.
        assert "a_ran" in state.data and state.data["a_ran"] is True
        assert state.data["__out__a"] == "out-a"
        assert "b_ran" in state.data
        assert "finish_ran" in state.data
        assert state.current_node == "finish"
        assert "a" in state.visited and "b" in state.visited
        assert state.visited.index("a") < state.visited.index("b")

        # El checkpoint final queda terminado y no pausado.
        ckpt = checkpointer.load(run_id="run-d", tenant_id="t1", session_id=None)
        assert ckpt["finished"] is True
        assert ckpt["paused"] is False
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# (e) resume de run pausado relanza GraphPaused
# --------------------------------------------------------------------------- #
def test_hil_resume_of_paused_run_relaunches_graph_paused():
    store, path = _make_store()
    try:
        checkpointer = GraphCheckpointStore(store)
        g = _build_hil_graph()
        runner = g.compile(checkpointer=checkpointer, tenant_id="t1")

        with pytest.raises(GraphPaused):
            asyncio.run(runner.run(run_id="run-e"))

        # resume sobre un run pausado vuelve a lanzar GraphPaused.
        with pytest.raises(GraphPaused) as excinfo:
            asyncio.run(runner.resume(run_id="run-e"))

        exc = excinfo.value
        assert exc.node_id == "a"
        assert exc.action == "approve:deploy"
        assert exc.run_id == "run-e"
    finally:
        store.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# (f) init_tracing in-memory + span_count >= 1 tras crear span
# --------------------------------------------------------------------------- #
def test_otel_init_tracing_in_memory_span_count_increments():
    if not OTEL_AVAILABLE:
        pytest.skip("opentelemetry no instalado en este entorno")

    import ciel.observability.otel as otel_mod

    saved = otel_mod._last_provider
    try:
        init_tracing(service_name="ciel-test")
        tracer = current_tracer()
        assert tracer is not None
        # Sin spans todavía (o al menos los previos); creamos uno.
        with tracer.start_as_current_span("fase8-span"):
            pass
        assert span_count() >= 1
    finally:
        otel_mod._last_provider = saved


# --------------------------------------------------------------------------- #
# (g) span_count devuelve -1 sin exporter in-memory
# --------------------------------------------------------------------------- #
def test_otel_span_count_returns_minus_one_without_in_memory_exporter():
    import ciel.observability.otel as otel_mod

    if not OTEL_AVAILABLE:
        # Sin OTel, span_count devuelve -1 por el primer guard.
        assert span_count() == -1
        return

    # Con OTel disponible, forzamos un provider cuyo exporter NO es
    # InMemorySpanExporter para ejercitar la rama "-1 (no medible)".
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )

    class _DummyExporter(SpanExporter):
        def export(self, spans):  # noqa: D401
            return SpanExportResult.SUCCESS

        def shutdown(self):
            return True

        def force_flush(self, timeout_millis=30000):  # pragma: no cover
            return True

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "no-mem"}))
    provider.add_span_processor(SimpleSpanProcessor(_DummyExporter()))

    saved = otel_mod._last_provider
    try:
        otel_mod._last_provider = provider
        assert span_count() == -1
    finally:
        otel_mod._last_provider = saved


# --------------------------------------------------------------------------- #
# (bonus) OtlpAuditExporter: write de un AuditEvent emite un span (in-memory)
# --------------------------------------------------------------------------- #
def test_otel_audit_exporter_write_creates_span():
    if not OTEL_AVAILABLE:
        pytest.skip("opentelemetry no instalado en este entorno")

    import ciel.observability.otel as otel_mod

    # init_tracing() puede llamarse una sola vez como provider global por
    # proceso (OpenTelemetry lo prohibe redefinir). Por eso usamos el provider
    # que DEVUELVE init_tracing y creamos el tracer a partir de ÉL, de modo
    # que el span del exporter caiga en el mismo exporter que inspecciona
    # span_count() (vía _last_provider).
    saved = otel_mod._last_provider
    try:
        provider = init_tracing(service_name="ciel-audit")
        tracer = provider.get_tracer("ciel-audit")
        exporter = OtlpAuditExporter(tracer=tracer)
        event = AuditEvent(
            event="agent.run",
            tenant_id="t1",
            session_id="s1",
            agent="agent-x",
            data={"goal": "do thing"},
        )
        asyncio.run(exporter.write(event))
        # El write debe haber producido al menos un span en el exporter in-memory.
        assert span_count() >= 1
    finally:
        otel_mod._last_provider = saved
