"""Canal-agnostic messaging adapters (Fase 8 — madurez de producción).

Este paquete extiende el contrato de ``ciel.gateway.adapter``
(``MessagingAdapter`` / ``Message``) con adapters concretos para Microsoft
Teams, Discord y Web UI, más un ``FakeAdapter`` totalmente offline usado por
los tests.

Todos los adapters son *runtime-agnostic* (no dependen de FastAPI ni de
``ciel.runtime``): ``send`` entrega un ``Message`` y ``receive`` es un async
generator que lo emite. El gateway los monta vía routers FastAPI
(``ciel.gateway``) que enqueuan eventos entrantes; los tests usan
``FakeAdapter`` para verificar el ciclo sin red.

OFFLINE-SAFE: ``TeamsAdapter`` y ``DiscordAdapter`` usan ``httpx`` (ya
dependencia base) para ``send``; si no hay red, ``send`` lanza de forma
controlada y los routers los alimentan vía webhook (sin red en tests).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Optional

from ciel.gateway.adapter import Message, MessagingAdapter

logger = logging.getLogger(__name__)


class FakeAdapter(MessagingAdapter):
    """Adapter de prueba totalmente offline (sin red).

    Implementa ``send`` y ``receive`` sobre colas ``asyncio.Queue`` internas.
    Los tests lo usan para verificar el ciclo send/receive de cualquier
    consumidor sin tocar la red.
    """

    def __init__(self) -> None:
        self._inbound: "asyncio.Queue[Message]" = asyncio.Queue()
        self._sent: list[Message] = []
        self._received: list[Message] = []

    async def send(self, message: Message) -> None:
        self._sent.append(message)
        # En un adapter real, send entrega a un canal externo. Aquí lo
        # simulamos poniéndolo también en inbound para permitir bucles de eco.
        await self._inbound.put(message)

    async def receive(self) -> AsyncIterator[Message]:
        while True:
            message = await self._inbound.get()
            self._received.append(message)
            yield message

    # -- helpers de inspección para tests -------------------------------
    def all_sent(self) -> list[Message]:
        return list(self._sent)

    def all_received(self) -> list[Message]:
        return list(self._received)

    async def receive_one(self) -> Message:
        """Drena y devuelve un único mensaje (conveniencia para tests)."""
        message = await self._inbound.get()
        self._received.append(message)
        return message

    def enqueue(self, message: Message) -> None:
        """Empuja un mensaje inbound (usado por los routers de gateway)."""
        self._inbound.put_nowait(message)


class TeamsAdapter(MessagingAdapter):
    """Adapter de Microsoft Teams vía Incoming Webhook (``send``).

    ``send`` hace ``POST {"text": content}`` a la ``webhook_url`` de un
    Incoming Webhook de Teams. ``receive`` se alimenta vía un router de
    webhook (``create_teams_webhook_router`` en ``ciel.gateway``) que enqueuea
    los eventos entrantes.

    OFFLINE-SAFE: si no hay red, ``send`` propaga el error de ``httpx`` de
    forma controlada; en tests se inyecta un ``client`` mock para verificar
    el payload sin red.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        *,
        channel: Optional[str] = None,
        client: Optional[object] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.channel = channel
        self._client = client  # inyectable para tests (httpx.AsyncClient mock)
        self._inbound: "asyncio.Queue[Message]" = asyncio.Queue()

    def _get_client(self):
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, message: Message) -> None:
        if not self.webhook_url:
            raise ValueError(
                "TeamsAdapter requires webhook_url to send (Incoming Webhook URL)."
            )
        client = self._get_client()
        payload = {"text": message.content}
        # httpx.AsyncClient.post o un mock con la misma firma.
        resp = await client.post(self.webhook_url, json=payload)
        # Si el cliente es un mock sin status_code, no validamos.
        status = getattr(resp, "status_code", 200)
        if status >= 400:
            raise RuntimeError(f"Teams webhook returned HTTP {status}")

    async def receive(self) -> AsyncIterator[Message]:
        while True:
            message = await self._inbound.get()
            yield message

    def enqueue(self, message: Message) -> None:
        self._inbound.put_nowait(message)


class DiscordAdapter(MessagingAdapter):
    """Adapter de Discord vía Webhook (``send``).

    ``send`` hace ``POST {"content": ...}`` a
    ``https://discord.com/api/webhooks/<id>/<token>``. ``receive`` se alimenta
    vía ``create_discord_webhook_router`` que enqueuea eventos
    ``MESSAGE_CREATE``.

    OFFLINE-SAFE: igual que TeamsAdapter, ``send`` propaga errores de red de
    forma controlada; en tests se inyecta un ``client`` mock.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        *,
        channel: Optional[str] = None,
        client: Optional[object] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.channel = channel
        self._client = client
        self._inbound: "asyncio.Queue[Message]" = asyncio.Queue()

    def _get_client(self):
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, message: Message) -> None:
        if not self.webhook_url:
            raise ValueError(
                "DiscordAdapter requires webhook_url to send (Discord webhook URL)."
            )
        client = self._get_client()
        payload = {"content": message.content}
        resp = await client.post(self.webhook_url, json=payload)
        status = getattr(resp, "status_code", 200)
        if status >= 400:
            raise RuntimeError(f"Discord webhook returned HTTP {status}")

    async def receive(self) -> AsyncIterator[Message]:
        while True:
            message = await self._inbound.get()
            yield message

    def enqueue(self, message: Message) -> None:
        self._inbound.put_nowait(message)


class WebUIAdapter(MessagingAdapter):
    """Adapter de Web UI (totalmente offline, sin red).

    ``send`` escribe a una cola de salida que la UI sondea (polling);
    ``receive`` lee de una cola de entrada alimentada por la UI. Útil para
    demos locales y para tests sin red.
    """

    def __init__(self) -> None:
        self._outbound: "asyncio.Queue[Message]" = asyncio.Queue()
        self._inbound: "asyncio.Queue[Message]" = asyncio.Queue()

    async def send(self, message: Message) -> None:
        # La UI sondea esta cola para mostrar mensajes salientes.
        self._outbound.put_nowait(message)

    async def receive(self) -> AsyncIterator[Message]:
        while True:
            message = await self._inbound.get()
            yield message

    def enqueue(self, message: Message) -> None:
        self._inbound.put_nowait(message)

    async def poll_outbound(self) -> Message:
        """La UI llama esto para obtener el siguiente mensaje saliente."""
        return await self._outbound.get()


__all__ = [
    "Message",
    "MessagingAdapter",
    "FakeAdapter",
    "TeamsAdapter",
    "DiscordAdapter",
    "WebUIAdapter",
]
