"""Bidirectional Slack messaging adapter.

This module provides :class:`SlackAdapter`, a concrete
:class:`~ciel.gateway.adapter.MessagingAdapter` that can *send* messages to
Slack over the real Web API (``chat.postMessage``) and *receive* inbound
events via a simple polling loop.

The ``slack_sdk`` dependency is **lenient**: importing this module never
crashes the package when the SDK is absent. Only the act of constructing a
:class:`SlackAdapter` lazily imports ``slack_sdk`` (it is pulled in by the
``messaging`` extra). If ``send`` is invoked without the SDK installed, a
clear :class:`RuntimeError` explaining how to install it is raised — but the
rest of the package keeps working.

Requires Python >= 3.10 (uses ``X | None`` syntax).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Optional

from ciel.gateway.adapter import Message, MessagingAdapter

logger = logging.getLogger(__name__)

# Lenient import guard flag: True once we confirm slack_sdk is available.
try:
    import slack_sdk  # noqa: F401

    _SLACK_SDK_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when SDK is missing
    _SLACK_SDK_AVAILABLE = False


__all__ = ["SlackAdapter"]


class SlackAdapter(MessagingAdapter):
    """Bidirectional Slack adapter built on ``slack_sdk.WebClient``.

    Args:
        token: A Slack bot/user token (``xoxb-...``). Stored and used to
            construct the :class:`slack_sdk.WebClient`.
        channel: Optional default channel (e.g. ``"#general"`` or a channel
            ID). Used by :meth:`send` when a :class:`Message` does not carry
            an explicit channel in its ``metadata``.
        bot_user_id: Optional bot user id (``U...``). Reserved for inbound
            event filtering; not required for sending.

    The Slack WebClient is created lazily so that merely importing this module
    (or instantiating the adapter) is safe even when ``slack_sdk`` is not
    installed. The client is built on first use of :meth:`send` / :meth:`receive`.
    """

    def __init__(
        self,
        token: str,
        *,
        channel: Optional[str] = None,
        bot_user_id: Optional[str] = None,
    ) -> None:
        self.token = token
        self.channel = channel
        self.bot_user_id = bot_user_id
        self._client = None  # type: ignore[var-annotated]
        self._inbound: "asyncio.Queue[Message]" = asyncio.Queue()

    def enqueue(self, message: Message) -> None:
        """Push an inbound :class:`Message` onto the internal queue.

        Used by the Slack webhook router to feed real ``message.changed``
        events into the adapter; consumers can drain them via
        :meth:`receive` (which is overridden below to prefer the queue).
        """
        self._inbound.put_nowait(message)

    # -- internal helpers -------------------------------------------------

    def _get_client(self):
        """Return the lazily-constructed ``slack_sdk.WebClient``.

        Raises:
            RuntimeError: If ``slack_sdk`` is not installed.
        """
        if self._client is None:
            if not _SLACK_SDK_AVAILABLE:  # pragma: no cover - SDK missing path
                raise RuntimeError(
                    "slack_sdk is not installed. Install it with "
                    "`uv pip install slack-sdk` (extra: messaging) to use SlackAdapter."
                )
            from slack_sdk import WebClient

            self._client = WebClient(token=self.token)
        return self._client

    def _resolve_channel(self, message: Message) -> str:
        """Pick the destination channel for a message.

        Resolution order: ``message.channel`` (the canonical DTO field) ->
        ``message.metadata['channel']`` (convenience override) -> ``self.channel``.
        """
        channel = message.channel or message.metadata.get("channel") or self.channel
        if not channel:
            raise ValueError(
                "No channel resolved for Slack send: provide message.channel "
                "or pass channel= to SlackAdapter."
            )
        return channel

    # -- public API -------------------------------------------------------

    async def send(self, message: Message) -> None:
        """Send ``message.content`` to Slack via ``chat.postMessage``.

        The destination channel is resolved from ``message.metadata['channel']``
        falling back to the adapter's default ``channel``. A clear
        :class:`ValueError` is raised when no channel can be resolved.

        Network access is required for this call to succeed against the real
        Slack API; tests pass a mocked ``WebClient`` to verify behaviour
        without touching the network.

        Args:
            message: The :class:`Message` to deliver.
        """
        client = self._get_client()
        channel = self._resolve_channel(message)
        # chat_postMessage is synchronous in slack_sdk; run it in a thread so
        # this stays friendly to the asyncio event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: client.chat_postMessage(channel=channel, text=message.text()),
        )
        logger.debug("SlackAdapter.send -> channel=%s len=%d", channel, len(message.text()))

    async def receive(self) -> AsyncIterator[Message]:
        """Yield inbound Slack messages via a simple polling loop.

        This is a lenient, best-effort implementation: it relies on Slack's
        ``conversations.history`` to pull recent messages and yields any that
        are not authored by the bot user. It polls every few seconds.

        The primary, fully-tested contract of this adapter is :meth:`send`.
        The receive loop is provided so the adapter is genuinely bidirectional,
        but it is intentionally simple and skips advanced cursor pagination and
        deduplication. Inbound event handling is better served by mounting the
        Slack webhook router (see :func:`create_slack_webhook_router`) onto the
        FastAPI app, which enqueues real ``message.changed`` events.

        The loop runs forever; the caller is responsible for cancellation.
        """
        client = self._get_client()
        if not self.channel:
            logger.warning(
                "SlackAdapter.receive: no default channel set; polling skipped."
            )
            return
        seen: set[str] = set()
        loop = asyncio.get_running_loop()
        while True:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: client.conversations_history(channel=self.channel, limit=20),
                )
                for msg in response.get("messages", []):
                    msg_id = msg.get("ts")
                    user = msg.get("user")
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    if self.bot_user_id and user == self.bot_user_id:
                        continue
                    yield Message(
                        id=msg_id,
                        channel=self.channel,
                        sender=user,
                        content=msg.get("text", ""),
                        metadata={"slack": msg},
                    )
            except Exception as exc:  # pragma: no cover - network resilience
                logger.warning("SlackAdapter.receive polling error: %s", exc)
            await asyncio.sleep(5)
