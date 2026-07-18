from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class MessageSlice:
    keep_head: int
    keep_tail: int
    removed: int
    summary: Optional[str] = None


class ContextCompressionError(Exception):
    """Raised when context compression arguments are invalid."""


def _split_system_message(messages: Sequence["ChatMessage"]) -> Tuple["ChatMessage", List["ChatMessage"], List["ChatMessage"]]:
    system_messages = [message for message in messages if message.role == "system"]
    if not system_messages:
        return None, [], list(messages)
    return system_messages[0], messages[1 : len(messages) - len(system_messages) + 1], list(messages)


def compress_context(
    messages: Sequence["ChatMessage"],
    max_chars: int = 20_000,
    *,
    keep_tail: int = 8,
) -> Tuple[List["ChatMessage"], MessageSlice]:
    """Simple context compression by head/tail window + rewrite.

    Keeps the first system message, the last ``keep_tail`` messages,
    and inserts a rewrite hint replacing removed middle content.
    """
    from ciel.runtime import ChatMessage

    if keep_tail < 1:
        raise ContextCompressionError("keep_tail must be >= 1")
    if not messages:
        raise ContextCompressionError("messages must not be empty")

    total = sum(len(message.text()) for message in messages)
    if total <= max_chars:
        return list(messages), MessageSlice(keep_head=len(messages), keep_tail=keep_tail, removed=0)

    system_message, middle, tail = _split_system_message(messages)
    kept_tail = tail[-keep_tail:] if tail else []
    if middle or system_message:
        removed = max(0, len(middle) - max(0, len(kept_tail)))
        hint = ChatMessage(
            role="system",
            content=f"[Context compressed; {removed} prior message(s) omitted for brevity.]",
        )
        compressed: List[ChatMessage] = ([system_message] if system_message else []) + [hint] + kept_tail
        return compressed, MessageSlice(
            keep_head=(1 if system_message else 0) + 1 + len(kept_tail),
            keep_tail=len(kept_tail),
            removed=removed,
            summary=hint.content,
        )

    return list(messages), MessageSlice(keep_head=len(messages), keep_tail=len(kept_tail), removed=0)
