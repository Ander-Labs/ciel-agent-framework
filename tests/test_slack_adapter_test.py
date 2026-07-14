"""Tests for the bidirectional Slack adapter.

The ``slack_sdk`` dependency is optional (``messaging`` extra). When it is not
installed the adapter must still import cleanly, and ``send`` must raise a
clear ``RuntimeError`` instead of crashing the package. When it *is* installed
we verify that ``send`` calls ``chat_postMessage`` with the resolved channel
and text, using a fake ``WebClient`` (no network).
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from ciel.gateway.adapter import Message
from ciel.gateway.adapter_slack import SlackAdapter, _SLACK_SDK_AVAILABLE


def _install_fake_slack_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake ``slack_sdk`` module with a recording WebClient."""
    fake = types.ModuleType("slack_sdk")

    class _Call:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeWebClient:
        def __init__(self, token: str = "") -> None:
            self.token = token
            self.postMessage_calls: list[_Call] = []

        def chat_postMessage(self, **kwargs: object) -> _Call:
            call = _Call(**kwargs)
            self.postMessage_calls.append(call)
            return call

    fake.WebClient = FakeWebClient
    monkeypatch.setitem(sys.modules, "slack_sdk", fake)
    monkeypatch.setattr("ciel.gateway.adapter_slack._SLACK_SDK_AVAILABLE", True)


def test_adapter_imports_without_sdk() -> None:
    # Importing the module must never fail, even if slack_sdk is absent.
    assert SlackAdapter is not None


def test_send_raises_clear_error_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    if _SLACK_SDK_AVAILABLE:
        pytest.skip("slack_sdk is installed; cannot simulate absence")
    adapter = SlackAdapter(token="xoxb-test", channel="#general")
    msg = Message(id="1", channel="#general", sender="u", content="hi")
    with pytest.raises(RuntimeError):
        asyncio.run(adapter.send(msg))


def test_send_calls_chat_post_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_slack_sdk(monkeypatch)
    adapter = SlackAdapter(token="xoxb-test", channel="#default")
    msg = Message(id="m1", channel="#ops", sender="u1", content="hello slack")

    asyncio.run(adapter.send(msg))

    client = adapter._client
    assert client is not None
    assert len(client.postMessage_calls) == 1
    call = client.postMessage_calls[0]
    assert call.kwargs["channel"] == "#ops"
    assert call.kwargs["text"] == "hello slack"


def test_send_falls_back_to_default_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_slack_sdk(monkeypatch)
    adapter = SlackAdapter(token="xoxb-test", channel="#fallback")
    msg = Message(id="m2", channel=None, sender="u2", content="no channel in msg")

    asyncio.run(adapter.send(msg))

    call = adapter._client.postMessage_calls[0]
    assert call.kwargs["channel"] == "#fallback"


def test_enqueue_pushes_message_onto_internal_queue() -> None:
    # The webhook router relies on enqueue() to feed inbound events.
    adapter = SlackAdapter(token="xoxb-test", channel="#general")
    msg = Message(id="q1", channel="#general", sender="u1", content="queued")

    adapter.enqueue(msg)

    # Drain the queue without running the full receive() poll loop.
    drained = asyncio.run(adapter._inbound.get())
    assert drained is msg
    assert drained.id == "q1"


def test_url_verification_challenge_responds() -> None:
    # The Slack webhook router must answer the url_verification handshake.
    from ciel.gateway import create_slack_webhook_router
    from fastapi.testclient import TestClient

    adapter = SlackAdapter(token="xoxb-test", channel="#general")
    router = create_slack_webhook_router(adapter, path="/slack")
    app = __import__("fastapi").FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/slack", json={"type": "url_verification", "challenge": "abc123"})
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}


def test_event_callback_message_is_enqueued() -> None:
    # A plain `message` event (no subtype) should be converted to a Message
    # and pushed onto the adapter's queue by the router.
    from ciel.gateway import create_slack_webhook_router
    from fastapi.testclient import TestClient

    adapter = SlackAdapter(token="xoxb-test", channel="#general")
    router = create_slack_webhook_router(adapter, path="/slack")
    app = __import__("fastapi").FastAPI()
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "type": "event_callback",
        "team_id": "T123",
        "event": {
            "type": "message",
            "channel": "#general",
            "user": "U123",
            "text": "hello bot",
            "client_msg_id": "msg-1",
            "ts": "123.456",
        },
    }
    resp = client.post("/slack", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["id"] == "msg-1"

    queued = asyncio.run(adapter._inbound.get())
    assert queued.channel == "#general"
    assert queued.sender == "U123"
    assert queued.content == "hello bot"
    assert queued.metadata["team"] == "T123"
    assert queued.metadata["slack_event"]["type"] == "message"
