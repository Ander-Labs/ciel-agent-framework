"""Tests formales para la Fase 8 — adapters de mensajería y routers de gateway.

Cubre los adapters concretos de canal (``ciel.adapters``: ``FakeAdapter``,
``TeamsAdapter``, ``DiscordAdapter``, ``WebUIAdapter``) y los routers HTTP de
ingesta de webhooks (``ciel.gateway.messaging``: teams / discord / webui).

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). OFFLINE-SAFE: para
``TeamsAdapter``/``DiscordAdapter`` se inyecta un ``client`` mock con la misma
firma que ``httpx.AsyncClient.post`` (async, devuelve objeto con
``status_code``); no se toca la red. Para los routers se usa ``TestClient`` de
FastAPI montando el router sobre un ``FastAPI`` app.

NOTA: las firmas reales se respetan EXACTAMENTE (verificadas contra el
código fuente, no contra suposiciones):
- ``Message(id, channel, sender, content, metadata=None)`` (dataclass frozen).
- ``FakeAdapter.send(Message)`` -> _sent + _inbound; ``receive_one()`` drena.
- ``TeamsAdapter(webhook_url=None, *, channel=None, client=None)``; send POST
  ``{"text": content}``; sin webhook_url -> ValueError.
- ``DiscordAdapter`` análogo con ``{"content": ...}``.
- ``WebUIAdapter.send(Message)`` -> _outbound; ``poll_outbound()`` drena.
- ``create_*_webhook_router(adapter, *, path=...)`` -> APIRouter.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ciel.adapters import (
    DiscordAdapter,
    FakeAdapter,
    TeamsAdapter,
    WebUIAdapter,
)
from ciel.gateway.adapter import Message
from ciel.gateway.messaging import (
    create_discord_webhook_router,
    create_teams_webhook_router,
    create_webui_router,
)


# --------------------------------------------------------------------------- #
# Helpers: cliente httpx mock (async, con .post(url, json=...))
# --------------------------------------------------------------------------- #
class _MockResponse:
    """Imita la respuesta de httpx.AsyncClient.post."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _MockHttpClient:
    """Mock de ``httpx.AsyncClient``: captura las llamadas a ``post``.

    La firma ``post(url, json=...)`` es async y devuelve un objeto con
    ``status_code``, exactamente lo que esperan TeamsAdapter/DiscordAdapter.
    """

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: List[Tuple[str, Any]] = []

    async def post(self, url: str, json: Any = None) -> _MockResponse:
        self.calls.append((url, json))
        return _MockResponse(self.status_code)


def _msg(channel: str, content: str, *, id: str = "m1", sender: str = "tester") -> Message:
    return Message(id=id, channel=channel, sender=sender, content=content)


# --------------------------------------------------------------------------- #
# (a) FakeAdapter send/receive round-trip
# --------------------------------------------------------------------------- #
def test_fake_adapter_send_receive_roundtrip():
    adapter = FakeAdapter()
    msg = _msg("fake", "hola mundo", id="a1")

    # send pone en _sent y en _inbound.
    asyncio.run(adapter.send(msg))
    assert adapter.all_sent() == [msg]
    assert len(adapter.all_sent()) == 1

    # receive_one drena uno de _inbound y lo registra en _received.
    got = asyncio.run(adapter.receive_one())
    assert got == msg
    assert adapter.all_received() == [msg]


def test_fake_adapter_enqueue_feeds_inbound():
    adapter = FakeAdapter()
    msg = _msg("fake", "encolado", id="a2")

    # enqueue empuja a _inbound sin pasar por _sent.
    adapter.enqueue(msg)
    assert adapter.all_sent() == []  # enqueue NO registra en _sent
    got = asyncio.run(adapter.receive_one())
    assert got == msg
    assert adapter.all_received() == [msg]


# --------------------------------------------------------------------------- #
# (b) TeamsAdapter send POST payload {"text": ...} y ValueError sin webhook_url
# --------------------------------------------------------------------------- #
def test_teams_adapter_send_posts_text_payload():
    client = _MockHttpClient(status_code=200)
    adapter = TeamsAdapter(webhook_url="https://hooks.example/teams", client=client)
    msg = _msg("teams", "mensaje teams", id="t1")

    asyncio.run(adapter.send(msg))

    # Se hizo exactamente un POST con la URL del webhook...
    assert len(client.calls) == 1
    url, payload = client.calls[0]
    assert url == "https://hooks.example/teams"
    # ...y el payload es {"text": content} (forma de Incoming Webhook de Teams).
    assert payload == {"text": "mensaje teams"}


def test_teams_adapter_send_without_webhook_url_raises_valueerror():
    adapter = TeamsAdapter()  # sin webhook_url
    msg = _msg("teams", "no deberia enviarse", id="t2")

    with pytest.raises(ValueError):
        asyncio.run(adapter.send(msg))


# --------------------------------------------------------------------------- #
# (c) DiscordAdapter send POST payload {"content": ...} y ValueError sin webhook
# --------------------------------------------------------------------------- #
def test_discord_adapter_send_posts_content_payload():
    client = _MockHttpClient(status_code=200)
    adapter = DiscordAdapter(webhook_url="https://discord.com/api/webhooks/x/y", client=client)
    msg = _msg("discord", "mensaje discord", id="d1")

    asyncio.run(adapter.send(msg))

    assert len(client.calls) == 1
    url, payload = client.calls[0]
    assert url == "https://discord.com/api/webhooks/x/y"
    # Discord espera {"content": ...}.
    assert payload == {"content": "mensaje discord"}


def test_discord_adapter_send_without_webhook_url_raises_valueerror():
    adapter = DiscordAdapter()  # sin webhook_url
    msg = _msg("discord", "no deberia enviarse", id="d2")

    with pytest.raises(ValueError):
        asyncio.run(adapter.send(msg))


# --------------------------------------------------------------------------- #
# (d) WebUIAdapter send / poll_outbound round-trip
# --------------------------------------------------------------------------- #
def test_webui_adapter_send_poll_outbound_roundtrip():
    adapter = WebUIAdapter()
    msg = _msg("webui", "respuesta ui", id="w1")

    # send escribe a _outbound (la UI lo sondea).
    asyncio.run(adapter.send(msg))
    got = asyncio.run(adapter.poll_outbound())
    assert got == msg
    assert got.content == "respuesta ui"
    assert got.id == "w1"


# --------------------------------------------------------------------------- #
# (e) Router Teams: POST enqueuea en adapter y GET health 200
# --------------------------------------------------------------------------- #
def test_teams_router_post_enqueues_and_health_ok():
    adapter = FakeAdapter()
    app = FastAPI()
    app.include_router(create_teams_webhook_router(adapter, path="/v1/messaging/teams"))
    client = TestClient(app)

    resp = client.post(
        "/v1/messaging/teams",
        json={"text": "hola teams", "from": {"id": "user-42"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert isinstance(body["id"], str) and body["id"]

    # El POST enqueueo un Message(channel="teams") en el adapter.
    enqueued = asyncio.run(adapter.receive_one())
    assert enqueued.channel == "teams"
    assert enqueued.content == "hola teams"
    assert enqueued.sender == "user-42"

    # Health endpoint.
    health = client.get("/v1/messaging/teams/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "channel": "teams"}


def test_teams_router_post_missing_text_rejected():
    adapter = FakeAdapter()
    app = FastAPI()
    app.include_router(create_teams_webhook_router(adapter, path="/v1/messaging/teams"))
    client = TestClient(app)

    # Sin "text" el router rechaza el payload.
    resp = client.post("/v1/messaging/teams", json={"from": {"id": "x"}})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


# --------------------------------------------------------------------------- #
# (f) Router Discord: ping type==1 y POST con content
# --------------------------------------------------------------------------- #
def test_discord_router_ping_returns_type_1():
    adapter = FakeAdapter()
    app = FastAPI()
    app.include_router(create_discord_webhook_router(adapter, path="/v1/messaging/discord"))
    client = TestClient(app)

    # Discord envía type==1 como ping de verificación de interacción.
    resp = client.post("/v1/messaging/discord", json={"type": 1})
    assert resp.status_code == 200
    assert resp.json() == {"type": 1}


def test_discord_router_post_content_enqueues():
    adapter = FakeAdapter()
    app = FastAPI()
    app.include_router(create_discord_webhook_router(adapter, path="/v1/messaging/discord"))
    client = TestClient(app)

    resp = client.post(
        "/v1/messaging/discord",
        json={"content": "ping de usuario", "author": {"username": "bob"}, "id": "d-msg-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["id"] == "d-msg-1"

    enqueued = asyncio.run(adapter.receive_one())
    assert enqueued.channel == "discord"
    assert enqueued.content == "ping de usuario"
    assert enqueued.sender == "bob"


# --------------------------------------------------------------------------- #
# (g) Router WebUI: POST enqueuea y GET /outbound devuelve mensaje
# --------------------------------------------------------------------------- #
def test_webui_router_post_enqueues_and_outbound_polls():
    # WebUIAdapter es necesario para que GET /outbound devuelva el mensaje
    # saliente (el router lo lee de adapter._outbound).
    adapter = WebUIAdapter()
    app = FastAPI()
    app.include_router(create_webui_router(adapter, path="/v1/messaging/webui"))
    client = TestClient(app)

    # POST enqueuea un Message(channel="webui") en el adapter.
    resp = client.post(
        "/v1/messaging/webui",
        json={"content": "entrada ui", "sender": "alice", "metadata": {"k": "v"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert isinstance(body["id"], str) and body["id"]

    # El router enqueuea en adapter._inbound (cola asyncio del adapter).
    enqueued = asyncio.run(adapter._inbound.get())
    assert enqueued.channel == "webui"
    assert enqueued.content == "entrada ui"
    assert enqueued.sender == "alice"
    assert enqueued.metadata == {"k": "v"}

    # Colocamos un mensaje saliente (el runtime lo envía vía adapter.send)...
    asyncio.run(adapter.send(_msg("webui", "respuesta del bot", id="w-out-1", sender="bot")))

    # ...y GET /outbound lo sondea.
    out = client.get("/v1/messaging/webui/outbound")
    assert out.status_code == 200
    ob = out.json()
    assert ob["status"] == "ok"
    assert ob["content"] == "respuesta del bot"
    assert ob["id"] == "w-out-1"
    assert ob["sender"] == "bot"


def test_webui_router_outbound_empty_returns_no_content():
    adapter = WebUIAdapter()
    app = FastAPI()
    app.include_router(create_webui_router(adapter, path="/v1/messaging/webui"))
    client = TestClient(app)

    # Sin mensajes salientes, el polling devuelve no_content (204-equivalente).
    out = client.get("/v1/messaging/webui/outbound")
    assert out.status_code == 200
    assert out.json()["status"] == "no_content"


def test_webui_router_health_ok():
    adapter = WebUIAdapter()
    app = FastAPI()
    app.include_router(create_webui_router(adapter, path="/v1/messaging/webui"))
    client = TestClient(app)

    health = client.get("/v1/messaging/webui/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "channel": "webui"}
