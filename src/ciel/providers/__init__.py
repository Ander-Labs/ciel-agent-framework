from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Type

import httpx

from ciel.common import CielError, ProviderError


_domain_error = ProviderError


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    capabilities: Sequence[str] = ()
    context_window: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    timeout: float = 30.0
    tenant: Optional[str] = None


class ChatProvider(ABC):
    provider_name: str = "unknown"

    @abstractmethod
    async def complete(self, request: "ChatRequest") -> "ChatResponse":
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: "ChatRequest") -> Sequence["ChatResponse"]:
        raise NotImplementedError

    @abstractmethod
    async def models(self) -> Sequence[ModelInfo]:
        raise NotImplementedError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, ChatProvider] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, provider: ChatProvider, *, config: Optional[Dict[str, Any]] = None) -> None:
        self._providers[name] = provider
        self._configs[name] = config or {}

    def get(self, name: str) -> ChatProvider:
        if name not in self._providers:
            raise _domain_error(f"Provider not registered: {name}")
        return self._providers[name]

    def available(self) -> Sequence[str]:
        return list(self._providers.keys())


class ProviderFactory:
    @staticmethod
    def from_config(config: ProviderConfig) -> ChatProvider:
        normalized = config.base_url.rstrip("/")
        if config.name == "litellm":
            from ciel.providers.litellm import LiteLLMProvider

            return LiteLLMProvider(
                model=config.default_model or "gpt-4o-mini",
                api_key=config.api_key,
                api_base=config.base_url if config.base_url else None,
                tenant=config.tenant,
                timeout=config.timeout,
            )
        if normalized.endswith("/v1") or "openai" in normalized:
            return OpenAICompatibleProvider(
                base_url=normalized,
                api_key=config.api_key,
                default_model=config.default_model,
                timeout=config.timeout,
                tenant=config.tenant,
            )
        raise ProviderError(f"No provider implementation for base_url: {config.base_url}")


@dataclass
class _ChatMessage:
    role: str
    content: str
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _ChatResponse:
    message: _ChatMessage
    finish_reason: str = "stop"
    metadata: Dict[str, Any] = field(default_factory=dict)


def _normalize_content_parts(content: Any) -> List[Dict[str, Any]]:
    """Normalize ``str | list[dict]`` content to OpenAI content-parts.

    - ``str`` -> ``[{"type": "text", "text": <content>}]``
    - ``list`` -> validated list of part dicts (text/image_url/input_audio/...),
      tolerating a bare ``{"text": ...}`` part by promoting it to a text part.
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        parts: List[Dict[str, Any]] = []
        for part in content:
            if isinstance(part, dict):
                if "type" not in part and "text" in part:
                    part = {"type": "text", "text": part["text"]}
                parts.append(part)
        return parts
    return [{"type": "text", "text": ""}]


def _serialize_chat_message(message: Dict[str, Any]) -> Dict[str, Any]:
    content = message.get("content", "")
    payload: Dict[str, Any] = {"role": message["role"], "content": _normalize_content_parts(content)}
    name = message.get("name")
    if name:
        payload["name"] = name
    return payload


def _build_chat_message(payload: Dict[str, Any]) -> _ChatMessage:
    return _ChatMessage(
        role=payload["role"],
        content=payload.get("content", "") or "",
        name=payload.get("name"),
        metadata=payload.get("metadata", {}),
    )


def _anthropic_content(content: Any) -> List[Dict[str, Any]]:
    """Normalize ``str | list[dict]`` content to Anthropic content blocks.

    - ``str`` -> ``[{"type": "text", "text": <content>}]``
    - ``list`` -> maps each part to Anthropic blocks:
        * ``{"type": "text", "text": ...}`` -> text block
        * ``{"type": "image_url", "image_url": {"url": "data:..."}}`` ->
          ``{"type": "image", "source": {"type": "base64", "media_type": ...,
          "data": <b64>}}`` (only data-URLs are supported by the API)
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return [{"type": "text", "text": ""}]
    blocks: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            text = part.get("text", "")
            if isinstance(text, str):
                blocks.append({"type": "text", "text": text})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            media_type, data = _split_data_url(url)
            if media_type is not None and data is not None:
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data},
                    }
                )
    return blocks or [{"type": "text", "text": ""}]


def _split_data_url(url: str) -> Tuple[Optional[str], Optional[str]]:
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


class OpenAICompatibleProvider(ChatProvider):
    provider_name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: float = 30.0,
        tenant: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.tenant = tenant

    def _client_ctx(self):
        """Context manager yielding an ``httpx.AsyncClient`` for this provider."""
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def complete(self, request: "ChatRequest") -> "ChatResponse":
        model = request.model or self.default_model or "unknown"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": model,
            "messages": [_serialize_chat_message(asdict(message)) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        payload = {key: value for key, value in payload.items() if value is not None}

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        from ciel.runtime import ChatChoice, ChatMessage, ChatResponse
        choice = body["choices"][0]
        message = ChatMessage(
            role=choice["message"]["role"],
            content=choice["message"].get("content", ""),
            name=choice["message"].get("name"),
            tool_call_id=choice["message"].get("tool_call_id"),
            metadata=choice["message"].get("metadata", {}),
        )
        return ChatResponse(
            choice=ChatChoice(message=message, finish_reason=choice.get("finish_reason", "stop")),
            metadata=body.get("usage", {}),
        )

    async def stream(self, request: "ChatRequest") -> Sequence["ChatResponse"]:
        from ciel.runtime import ChatChoice, ChatMessage, ChatResponse

        model = request.model or self.default_model or "unknown"
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": model,
            "messages": [_serialize_chat_message(asdict(message)) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        payload = {key: value for key, value in payload.items() if value is not None}

        chunks: list["ChatResponse"] = []
        accumulated = ""
        finish_reason = "stop"

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            async with client.stream("POST", "/chat/completions", headers=headers, json=payload) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        accumulated += piece
                    if choices[0].get("finish_reason") is not None:
                        finish_reason = choices[0].get("finish_reason") or "stop"
                    message = ChatMessage(
                        role="assistant",
                        content=accumulated,
                        metadata={"tenant": self.tenant},
                    )
                    chunks.append(
                        ChatResponse(
                            choice=ChatChoice(message=message, finish_reason=finish_reason),
                            metadata={"tenant": self.tenant, "streaming": True},
                        )
                    )
        return tuple(chunks)

    async def models(self) -> Sequence[ModelInfo]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                response = await client.get("/models", headers=headers)
                response.raise_for_status()
                body = response.json()
            model_ids = [item.get("id") for item in body.get("data", []) if item.get("id")]
            if model_ids:
                return [ModelInfo(id=item, provider=self.provider_name, metadata={"tenant": self.tenant}) for item in model_ids]
        except Exception as exc:  # pragma: no cover - network failure path
            raise _domain_error(f"Failed to list models: {exc}") from exc
        return [ModelInfo(id=self.default_model or "unknown", provider=self.provider_name, metadata={"tenant": self.tenant})]


class AnthropicProvider(ChatProvider):
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-3-5-haiku-20241022",
        tenant: Optional[str] = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.tenant = tenant
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def complete(self, request: "ChatRequest") -> "ChatResponse":
        if self.api_key is None:
            raise _domain_error("Anthropic provider requires api_key")
        model = request.model or self.default_model
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
        }
        messages = [
            {"role": message.role, "content": _anthropic_content(message.content)}
            for message in request.messages
        ]
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 64,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/messages", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        content = self._extract_text(body)
        choice = _ChatResponse(
            message=_ChatMessage(role="assistant", content=content, metadata={}),
            finish_reason="stop",
            metadata=body,
        )
        from ciel.runtime import ChatResponse as ChatResponseDTO
        return ChatResponseDTO(choice=choice, metadata={"provider": self.provider_name})

    async def stream(self, request: "ChatRequest") -> Sequence["ChatResponse"]:
        return [await self.complete(request)]

    async def models(self) -> Sequence["ModelInfo"]:
        return [ModelInfo(id=self.default_model, provider=self.provider_name, metadata={"tenant": self.tenant})]

    @staticmethod
    def _extract_text(body: Dict[str, Any]) -> str:
        items = body.get("content") or []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if isinstance(text, str):
                    return text
        return ""


# LiteLLM meta-provider is an optional extra; import it lazily so the core
# providers module stays usable without the heavy ``litellm`` dependency.
try:  # pragma: no cover - depends on extras install
    from ciel.providers.litellm import LiteLLMProvider
except ImportError:
    LiteLLMProvider = None  # type: ignore[assignment]
