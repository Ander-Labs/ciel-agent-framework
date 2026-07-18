"""Google Gemini provider (Generative Language API).

Offline-safe: only performs HTTP when an api_key is configured; in tests a mock
httpx client can be injected. Mirrors the ChatProvider contract used by the
OpenAI/Anthropic providers.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import httpx

from ciel.common import ProviderError
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse


class GeminiProvider(ChatProvider):
    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        default_model: str = "gemini-1.5-flash",
        tenant: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.tenant = tenant
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    def _client_ctx(self):
        if self._client is not None:
            return _NullCtx(self._client)
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self.api_key is None:
            raise ProviderError("Gemini provider requires api_key")
        model = request.model or self.default_model
        payload = self._to_gemini(request)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        async with self._client_ctx() as client:
            response = await client.post(
                f"/models/{model}:generateContent", headers=headers, json=payload
            )
            response.raise_for_status()
            body = response.json()
        text = self._extract_text(body)
        message = ChatMessage(role="assistant", content=text, metadata={"tenant": self.tenant})
        return ChatResponse(
            choice=ChatChoice(message=message, finish_reason="stop"),
            metadata={"provider": self.provider_name},
        )

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:
        # Gemini streaming would use :streamGenerateContent; fall back to complete.
        return [await self.complete(request)]

    async def models(self) -> Sequence[ModelInfo]:
        return [ModelInfo(id=self.default_model, provider=self.provider_name, metadata={"tenant": self.tenant})]

    @staticmethod
    def _to_gemini(request: ChatRequest) -> dict[str, Any]:
        contents = []
        for message in request.messages:
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": _gemini_parts(message.content)})
        payload: dict[str, Any] = {"contents": contents}
        gen_cfg = {}
        if request.temperature is not None:
            gen_cfg["temperature"] = request.temperature
        if request.max_tokens is not None:
            gen_cfg["maxOutputTokens"] = request.max_tokens
        if gen_cfg:
            payload["generationConfig"] = gen_cfg
        return payload

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        candidates = body.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", []) or []
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict))


def _gemini_parts(content: Any) -> List[Dict[str, Any]]:
    """Normalize ``str | list[dict]`` content to Gemini parts.

    - ``str`` -> ``[{"text": <content>}]``
    - ``list`` -> maps each part to a Gemini part:
        * ``{"type": "text", "text": ...}`` -> ``{"text": ...}``
        * ``{"type": "image_url", "image_url": {"url": "data:..."}}`` ->
          ``{"inline_data": {"mime_type": ..., "data": <b64>}}``
    """
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        return [{"text": ""}]
    parts: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            text = part.get("text", "")
            if isinstance(text, str):
                parts.append({"text": text})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            mime, data = _split_data_url(url)
            if mime is not None and data is not None:
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
    return parts or [{"text": ""}]


def _split_data_url(url: str) -> "tuple[Optional[str], Optional[str]]":
    """Split a ``data:<mime>;base64,<data>`` URL into (mime, b64)."""
    if not isinstance(url, str) or not url.startswith("data:"):
        return None, None
    try:
        meta, data = url[5:].split(",", 1)
    except ValueError:
        return None, None
    if ";base64" not in meta:
        return None, None
    mime = meta.split(";base64", 1)[0] or "application/octet-stream"
    return mime, data


class _NullCtx:
    """Context manager that yields an injected client without closing it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *exc: Any) -> None:
        return None
