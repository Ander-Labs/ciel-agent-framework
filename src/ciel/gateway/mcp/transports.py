from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence


class MCPTransport(ABC):
    @abstractmethod
    async def send(self, message: Mapping[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def receive(self) -> AsyncIterator[Mapping[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class MCPStdioTransport(MCPTransport):
    def __init__(self, *, stdout_write: Any, stdin_readline: Any) -> None:
        self._stdout = stdout_write
        self._stdin = stdin_readline

    async def send(self, message: Mapping[str, Any]) -> None:
        self._stdout.write(json.dumps(message) + "\n")
        self._stdout.flush()

    async def receive(self) -> AsyncIterator[Mapping[str, Any]]:
        while True:
            line = await self._stdin()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    async def close(self) -> None:
        return None


class MCPHTTPTransport(MCPTransport):
    def __init__(self, *, base_url: str, client: Any) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def send(self, message: Mapping[str, Any]) -> None:
        await self._client.post(f"{self._base_url}/mcp", json=message)

    async def receive(self) -> AsyncIterator[Mapping[str, Any]]:
        response = await self._client.get(f"{self._base_url}/mcp/events")
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    async def close(self) -> None:
        await self._client.aclose()
