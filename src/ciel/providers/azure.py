"""Azure OpenAI provider (Fase 16-B).

Azure OpenAI is OpenAI-compatible but requires the ``api-version`` query
parameter and addresses a *deployment* name rather than the raw model id.
This subclass injects the api-version on every request and treats the model
field as the deployment name. Offline-safe: no network at construction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

import httpx

from ciel.common import ProviderError
from ciel.providers import ChatProvider, ModelInfo, OpenAICompatibleProvider
from ciel.providers import _normalize_content_parts
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse


class AzureOpenAIProvider(OpenAICompatibleProvider):
    provider_name = "azure_openai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: Optional[str] = None,
        api_version: str = "2024-06-01",
        deployment: Optional[str] = None,
        default_model: Optional[str] = None,
        tenant: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        # Azure base_url looks like https://<resource>.openai.azure.com
        super().__init__(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            default_model=deployment or default_model,
            timeout=timeout,
            tenant=tenant,
        )
        self.api_version = api_version
        self.deployment = deployment or default_model

    def _chat_path(self, model: str) -> str:
        deployment = self.deployment or model
        return f"/openai/deployments/{deployment}/chat/completions?api-version={self.api_version}"

    def _build_messages(self, request: ChatRequest) -> list[Dict[str, Any]]:
        return [
            {
                "role": m.role,
                "content": _normalize_content_parts(m.content),
                **({"name": m.name} if m.name else {}),
            }
            for m in request.messages
        ]

    async def complete(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.default_model or (self.deployment or "unknown")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key

        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        async with self._client_ctx() as client:
            response = await client.post(self._chat_path(model), headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        choice = body["choices"][0]
        message = ChatMessage(
            role=choice["message"].get("role", "assistant"),
            content=choice["message"].get("content", ""),
            name=choice["message"].get("name"),
            tool_call_id=choice["message"].get("tool_call_id"),
            metadata={"tenant": self.tenant, "provider": self.provider_name},
        )
        return ChatResponse(
            choice=ChatChoice(message=message, finish_reason=choice.get("finish_reason", "stop")),
            metadata=body.get("usage", {}),
        )

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:
        model = request.model or self.default_model or (self.deployment or "unknown")
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["api-key"] = self.api_key

        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        chunks: list[ChatResponse] = []
        accumulated = ""
        finish_reason = "stop"
        async with self._client_ctx() as client:
            async with client.stream("POST", self._chat_path(model), headers=headers, json=payload) as response:
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
                    chunks.append(
                        ChatResponse(
                            choice=ChatChoice(
                                message=ChatMessage(
                                    role="assistant",
                                    content=accumulated,
                                    metadata={"tenant": self.tenant, "provider": self.provider_name},
                                ),
                                finish_reason=finish_reason,
                            ),
                            metadata={"tenant": self.tenant, "streaming": True, "provider": self.provider_name},
                        )
                    )
        return tuple(chunks)

    async def models(self) -> Sequence[ModelInfo]:
        name = self.deployment or self.default_model or "unknown"
        return [ModelInfo(id=name, provider=self.provider_name, metadata={"tenant": self.tenant})]
