"""Tests offline de Ciel Studio (Fase 13 / F19).

Verifican el store en memoria, el enganche al Agent y el router FastAPI,
TODO sin red ni providers reales (usa echo provider / fakes).
"""

import asyncio

import pytest

from ciel.studio import (
    LoopRecord,
    SessionRecord,
    StudioStore,
    create_studio_router,
    get_studio_store,
    install_studio_support,
    reset_studio_store,
)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_studio_store()
    yield
    reset_studio_store()


def test_store_records_and_lists_sessions():
    st = StudioStore()
    st.record_session(tenant_id="acme", agent="a1", prompt="hola", text="hi", tool_calls=2, turns=3)
    sessions = st.list_sessions(tenant_id="acme")
    assert len(sessions) == 1
    rec = sessions[0]
    assert isinstance(rec, SessionRecord)
    assert rec.tenant_id == "acme"
    assert rec.tool_calls == 2
    assert rec.turns == 3


def test_store_isolates_tenants():
    st = StudioStore()
    st.record_session(tenant_id="acme", agent="a", prompt="x")
    st.record_session(tenant_id="other", agent="a", prompt="y")
    assert len(st.list_sessions(tenant_id="acme")) == 1
    assert len(st.list_sessions(tenant_id="other")) == 1
    assert len(st.list_sessions()) == 2  # sin filtro -> todas


def test_store_update_session():
    st = StudioStore()
    rec = st.record_session(tenant_id="acme", agent="a", text="v1")
    updated = st.update_session(rec.session_id, text="v2", finish_reason="tool_calls")
    assert updated is not None
    assert updated.text == "v2"
    assert updated.finish_reason == "tool_calls"
    # missing id -> None
    assert st.update_session("nope") is None


def test_store_loops():
    st = StudioStore()
    st.record_loop(tenant_id="acme", agent="a", status="running")
    st.record_loop(tenant_id="acme", agent="a", status="done")
    st.update_loop(st.list_loops(tenant_id="acme")[1].loop_id, steps=5)
    loops = st.list_loops(tenant_id="acme")
    assert len(loops) == 2
    assert all(isinstance(l, LoopRecord) for l in loops)
    snap = st.snapshot(tenant_id="acme")
    assert snap["counts"]["loops"] == 2
    assert snap["counts"]["running_loops"] == 1


def test_snapshot_serializes():
    st = StudioStore()
    st.record_session(tenant_id="acme", agent="a", prompt="p", text="t")
    snap = st.snapshot()
    assert "sessions" in snap and "loops" in snap and "counts" in snap
    sess = snap["sessions"][0]
    assert sess["type"] == "session"
    assert sess["prompt"] == "p"
    assert sess["text"] == "t"


def test_singleton_store():
    a = get_studio_store()
    b = get_studio_store()
    assert a is b
    a.record_session(tenant_id="x", agent="a")
    assert len(b.list_sessions()) == 1


# ---------------------------------------------------------------------------
# Enganche al Agent (usa echo provider offline)
# ---------------------------------------------------------------------------
def _make_echo_agent():
    """Construye un Agent mínimo con un echo provider fake (sin red)."""
    from ciel.api import Agent
    from ciel.runtime import ChatChoice, ChatMessage, ChatResponse

    class _EchoProvider:
        model = "echo"

        async def acomplete(self, request, **kw):
            msg = request.messages[-1].content if request.messages else ""
            choice = ChatChoice(
                message=ChatMessage(role="assistant", content=f"echo:{msg}"),
                finish_reason="stop",
            )
            return ChatResponse(choice=choice, metadata={})

        async def complete(self, request, **kw):
            return await self.acomplete(request, **kw)

    return Agent(provider=_EchoProvider(), tools=[], model="echo")


def test_install_studio_support_tracks_run():
    agent = _make_echo_agent()
    st = install_studio_support(agent)
    resp = agent.run("di hola", tenant_id="acme")
    assert isinstance(resp.text, str)
    sessions = st.list_sessions(tenant_id="acme")
    assert len(sessions) == 1
    assert sessions[0].prompt == "di hola"


def test_install_studio_support_tracks_arun():
    agent = _make_echo_agent()
    st = install_studio_support(agent)

    async def _go():
        return await agent.arun("async ping", tenant_id="acme")

    resp = asyncio.run(_go())
    assert isinstance(resp.text, str)
    assert len(st.list_sessions(tenant_id="acme")) == 1


# ---------------------------------------------------------------------------
# Router FastAPI (requiere extra 'server' / FastAPI)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    create_studio_router is None,
    reason="FastAPI no disponible",
)
def test_router_exposes_snapshot():
    from fastapi.testclient import TestClient

    st = StudioStore()
    st.record_session(tenant_id="acme", agent="a", prompt="p", text="t", tool_calls=1)
    router = create_studio_router(store=st)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/v1/studio")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["sessions"] == 1
    assert body["sessions"][0]["prompt"] == "p"

    r2 = client.get("/v1/studio/health")
    assert r2.json()["status"] == "ok"


@pytest.mark.skipif(
    create_studio_router is None,
    reason="FastAPI no disponible",
)
def test_router_filters_by_tenant():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    st = StudioStore()
    st.record_session(tenant_id="acme", agent="a", prompt="p")
    st.record_session(tenant_id="other", agent="a", prompt="q")
    app = FastAPI()
    app.include_router(create_studio_router(store=st))
    client = TestClient(app)
    r = client.get("/v1/studio/sessions?tenant=acme")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["tenant_id"] == "acme"
