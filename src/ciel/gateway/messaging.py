"""Webhook routers para adapters de canal (Fase 8 — Teams/Discord/Web UI).

Estos routers montan endpoints HTTP que convierten eventos entrantes de cada
canal en ``ciel.gateway.adapter.Message`` y los empujan (``enqueue``) al
adapter correspondiente, de forma que el runtime puede consumirlos vía
``adapter.receive()``. Siguen el mismo patrón que
``ciel.gateway.create_slack_webhook_router``.

OFFLINE-SAFE: los routers no requieren red para importarse ni para arrancar;
solo la entrega real de ``send`` (en los adapters) toca la red.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request

from ciel.gateway.adapter import Message

logger = logging.getLogger(__name__)


def create_teams_webhook_router(
    adapter,
    *,
    path: str = "/v1/messaging/teams",
    signing_secret: Optional[str] = None,
) -> APIRouter:
    """Router que ingiere eventos de Microsoft Teams al ``adapter``.

    Teams entrega cargas JSON con ``text`` (y opcionalmente ``from`` /
    ``channelData``). El router los convierte en ``Message`` y los enqueuea.
    Si se pasa ``signing_secret`` se puede validar la firma HMAC (fuera de
    alcance en smoke tests); sin él, se acepta el payload tal cual.
    """
    router = APIRouter()

    @router.post(path)
    async def teams_events(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"status": "rejected", "error": f"invalid json: {exc}"}

        text = payload.get("text") or payload.get("body") or ""
        if not text:
            return {"status": "rejected", "error": "missing text"}
        sender = payload.get("from", {}).get("id") if isinstance(payload.get("from"), dict) else payload.get("from")
        message = Message(
            id=payload.get("id") or str(__import__("uuid").uuid4()),
            channel="teams",
            sender=sender,
            content=text,
            metadata={"teams_event": payload},
        )
        enqueue = getattr(adapter, "enqueue", None)
        if callable(enqueue):
            enqueue(message)
        else:  # pragma: no cover - adapter sin enqueue
            logger.warning("TeamsAdapter has no enqueue(); dropping %s", message.id)
        return {"status": "accepted", "id": message.id}

    @router.get(f"{path}/health")
    async def teams_health():
        return {"status": "ok", "channel": "teams"}

    return router


def create_discord_webhook_router(
    adapter,
    *,
    path: str = "/v1/messaging/discord",
) -> APIRouter:
    """Router que ingiere eventos ``MESSAGE_CREATE`` de Discord al ``adapter``.

    Discord entrega un JSON con ``content``, ``author``/``id`` y ``channel_id``.
    El router lo convierte en ``Message`` y lo enqueuea.
    """
    router = APIRouter()

    @router.post(path)
    async def discord_events(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"status": "rejected", "error": f"invalid json: {exc}"}

        if payload.get("type") == 1:
            # Discord Ping (interacción): responde con el mismo id.
            return {"type": 1}

        content = payload.get("content", "")
        if not content:
            return {"status": "ok"}  # eventos sin contenido (presence, etc.)
        author = payload.get("author", {})
        sender = author.get("username") or author.get("id")
        message = Message(
            id=payload.get("id") or str(__import__("uuid").uuid4()),
            channel="discord",
            sender=sender,
            content=content,
            metadata={"discord_event": payload, "channel_id": payload.get("channel_id")},
        )
        enqueue = getattr(adapter, "enqueue", None)
        if callable(enqueue):
            enqueue(message)
        else:  # pragma: no cover - adapter sin enqueue
            logger.warning("DiscordAdapter has no enqueue(); dropping %s", message.id)
        return {"status": "accepted", "id": message.id}

    @router.get(f"{path}/health")
    async def discord_health():
        return {"status": "ok", "channel": "discord"}

    return router


def create_webui_router(
    adapter,
    *,
    path: str = "/v1/messaging/webui",
) -> APIRouter:
    """Router de Web UI: POST para enviar mensajes al runtime, GET para sondear.

    La UI hace ``POST {path}`` con un ``Message`` y lo enqueuea en el
    ``WebUIAdapter``; ``GET {path}/outbound`` sondea el siguiente mensaje
    saliente del adapter (polling).
    """
    from ciel.adapters import WebUIAdapter

    router = APIRouter()

    @router.post(path)
    async def webui_inbound(request: Request):
        try:
            payload = await request.json()
        except Exception as exc:
            return {"status": "rejected", "error": f"invalid json: {exc}"}
        content = payload.get("content")
        if not content:
            return {"status": "rejected", "error": "missing content"}
        message = Message(
            id=payload.get("id") or str(__import__("uuid").uuid4()),
            channel="webui",
            sender=payload.get("sender"),
            content=content,
            metadata=payload.get("metadata") or {},
        )
        enqueue = getattr(adapter, "enqueue", None)
        if callable(enqueue):
            enqueue(message)
        else:  # pragma: no cover - adapter sin enqueue
            logger.warning("WebUIAdapter has no enqueue(); dropping %s", message.id)
        return {"status": "accepted", "id": message.id}

    @router.get(f"{path}/outbound")
    async def webui_outbound():
        # Polling: devuelve el siguiente mensaje saliente o 204 si no hay.
        if not isinstance(adapter, WebUIAdapter):
            return {"status": "ok", "channel": "webui"}
        try:
            message = adapter._outbound.get_nowait()
        except Exception:
            return {"status": "no_content"}
        return {
            "status": "ok",
            "id": message.id,
            "content": message.text(),
            "sender": message.sender,
            "metadata": message.metadata,
        }

    @router.get(f"{path}/health")
    async def webui_health():
        return {"status": "ok", "channel": "webui"}

    return router
