"""Generic messaging adapter for webhook-based HTTP message intake.

This module is pure Python + asyncio. It does not depend on FastAPI,
``ciel.runtime``, or ``ciel.providers`` — it is runtime-agnostic so any
HTTP server (FastAPI, Starlette, aiohttp, etc.) can plug into it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

__all__ = ["Message", "MessagingAdapter", "WebhookAdapter"]


@dataclass(frozen=True)
class Message:
    """Immutable DTO representing a single inbound or outbound message.

    Attributes:
        id: Unique message identifier. Generated via ``uuid4`` when not
            supplied by the payload.
        channel: Logical channel the message arrived on (required).
        sender: Optional sender identifier (may be ``None``).
        content: Message body / content (required).
        metadata: Free-form metadata dict; defaults to an empty dict.
    """

    id: str
    channel: str
    sender: Optional[str]
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class MessagingAdapter:
    """Abstract base class for messaging adapters.

    Subclasses implement :meth:`receive` (an async generator yielding
    inbound :class:`Message` objects) and :meth:`send` (delivery of an
    outbound :class:`Message`).
    """

    async def receive(self) -> AsyncIterator[Message]:
        """Yield inbound messages as they arrive.

        Implementations should be async generators that block until a
        message is available and then ``yield`` it.
        """
        raise NotImplementedError
        yield  # pragma: no cover  # makes this a generator for type checkers

    async def send(self, message: Message) -> None:
        """Deliver an outbound message.

        Args:
            message: The :class:`Message` to send.
        """
        raise NotImplementedError


class WebhookAdapter(MessagingAdapter):
    """Messaging adapter that ingests messages via an HTTP webhook endpoint.

    Incoming webhook payloads are validated, converted to :class:`Message`
    instances, and enqueued on an internal :class:`asyncio.Queue`. The
    :meth:`receive` async generator drains the queue and yields messages
    to consumers.

    Typical usage alongside an HTTP framework::

        adapter = WebhookAdapter()

        @app.post("/webhook")
        async def webhook(request):
            payload = await request.json()
            return await adapter.handle_webhook(payload)

        async for message in adapter.receive():
            ...
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    # -- public API -------------------------------------------------

    async def handle_webhook(self, payload: dict) -> dict:
        """Validate a webhook payload, enqueue a :class:`Message`, and respond.

        Expected payload shape::

            {"id": "...", "channel": "...", "sender": "...",
             "content": "...", "metadata": {...}}

        ``channel`` and ``content`` are required. ``id`` is generated
        via :func:`uuid.uuid4` when absent. ``sender`` defaults to
        ``None`` and ``metadata`` defaults to an empty dict.

        Args:
            payload: Raw deserialized webhook body.

        Returns:
            ``{"status": "accepted", "id": <message id>}`` on success,
            or ``{"status": "rejected", "error": "missing required
            field: <field>"}`` when validation fails.
        """
        channel = payload.get("channel")
        content = payload.get("content")

        if not channel:
            return {"status": "rejected", "error": "missing required field: channel"}
        if not content:
            return {"status": "rejected", "error": "missing required field: content"}

        message = Message(
            id=payload.get("id") or str(uuid.uuid4()),
            channel=channel,
            sender=payload.get("sender"),
            content=content,
            metadata=payload.get("metadata") or {},
        )

        await self._queue.put(message)

        return {"status": "accepted", "id": message.id}

    async def receive(self) -> AsyncIterator[Message]:
        """Async generator yielding messages from the internal queue.

        Blocks indefinitely on each :meth:`asyncio.Queue.get` call until
        a message becomes available, then yields it. The loop runs
        forever — the caller is responsible for cancellation/timeout.
        """
        while True:
            message = await self._queue.get()
            yield message

    async def receive_internal(self) -> Message:
        """Drain and return a single message from the queue.

        Convenience method for consumers that prefer one-at-a-time
        polling over the async generator. Blocks until a message is
        available.

        Returns:
            The next :class:`Message` in the queue.
        """
        return await self._queue.get()

    async def send(self, message: Message) -> None:
        """Outbound send — not implemented for the webhook adapter.

        The webhook adapter is inbound-only by design. Subclass or
        compose with an outbound adapter if delivery is needed.
        """
        raise NotImplementedError
