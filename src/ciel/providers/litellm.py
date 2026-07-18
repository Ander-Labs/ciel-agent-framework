"""LiteLLM meta-provider (Fase 16-A).

Exposes 100+ models through a single :class:`ChatProvider` contract by
delegating to the ``litellm`` library. This module is **offline-safe**: it
never imports ``litellm`` at module load time, only when the provider is
actually constructed/used, so the default framework import graph stays free of
the heavy ``litellm`` dependency. Install it with the optional extra::

    pip install "mana-ciel[litellm]"

Fallback/load-balancing across multiple models is available via a LiteLLM
``Router`` (passed as ``models``); when omitted, a single model is used.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from ciel.common import ProviderError
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatRequest, ChatResponse


def _import_litellm():
    """Import ``litellm`` on demand; raise a clear error if it is missing."""
    try:
        import litellm  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on extras install
        raise ProviderError(
            "The 'litellm' extra is required for LiteLLMProvider. "
            "Install it with: pip install \"mana-ciel[litellm]\""
        ) from exc
    return litellm


def _build_litellm_messages(request: ChatRequest) -> List[Dict[str, Any]]:
    """Build LiteLLM's ``messages`` payload from a :class:`ChatRequest`.

    Reuses the OpenAI-compatible content normalization so multimodal content
    (text + image_url parts) is forwarded unchanged.
    """
    from ciel.providers import _normalize_content_parts

    messages: List[Dict[str, Any]] = []
    for message in request.messages:
        payload: Dict[str, Any] = {
            "role": message.role,
            "content": _normalize_content_parts(message.content),
        }
        if message.name:
            payload["name"] = message.name
        messages.append(payload)
    return messages


class LiteLLMProvider(ChatProvider):
    """ChatProvider backed by LiteLLM (100+ models, optional Router fallback)."""

    provider_name = "litellm"

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        models: Optional[Sequence[str]] = None,
        tenant: Optional[str] = None,
        timeout: float = 60.0,
        **litellm_kwargs: Any,
    ) -> None:
        # Eagerly import litellm so construction fails clearly when the extra
        # is missing (offline, no network needed — just module availability).
        try:
            self._litellm = _import_litellm()
        except ProviderError:
            raise
        except ImportError as exc:  # pragma: no cover - defensive
            raise ProviderError(
                "The 'litellm' extra is required for LiteLLMProvider. "
                "Install it with: pip install \"mana-ciel[litellm]\""
            ) from exc
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.tenant = tenant
        self.timeout = timeout
        self._litellm_kwargs = dict(litellm_kwargs)
        self._router = None
        if models:
            try:
                Router = self._litellm.Router
                self._router = Router(
                    model_list=[
                        {
                            "model_name": model,
                            "litellm_params": {
                                "model": m,
                                "api_key": api_key,
                                "api_base": api_base,
                                **litellm_kwargs,
                            },
                        }
                        for m in models
                    ]
                )
            except (ImportError, AttributeError):  # pragma: no cover
                self._router = None

    def _common_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"timeout": self.timeout, **self._litellm_kwargs}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs

    async def complete(self, request: ChatRequest) -> ChatResponse:
        messages = _build_litellm_messages(request)
        model = request.model or self.model
        kwargs = self._common_kwargs()
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        if self._router is not None:
            response = await self._router.acompletion(model=model, messages=messages, **kwargs)
        else:
            response = await self._litellm.acompletion(model=model, messages=messages, **kwargs)

        choice = response.choices[0]
        message = ChatMessage(
            role=choice.message.role or "assistant",
            content=choice.message.content or "",
            name=getattr(choice.message, "name", None),
            metadata={"tenant": self.tenant, "provider": self.provider_name},
        )
        return ChatResponse(
            choice=ChatChoice(
                message=message,
                finish_reason=getattr(choice, "finish_reason", "stop") or "stop",
                usage=getattr(response, "usage", None),
            ),
            metadata={"provider": self.provider_name},
        )

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:
        messages = _build_litellm_messages(request)
        model = request.model or self.model
        kwargs = self._common_kwargs()
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        kwargs["stream"] = True

        chunks: List[ChatResponse] = []
        accumulated = ""
        finish_reason = "stop"

        if self._router is not None:
            stream = self._router.acompletion(model=model, messages=messages, **kwargs)
        else:
            stream = self._litellm.acompletion(model=model, messages=messages, **kwargs)
        # LiteLLM returns the async generator directly when stream=True.
        if hasattr(stream, "__await__"):
            stream = await stream

        async for chunk in stream:
            delta = getattr(chunk.choices[0], "delta", None)
            piece = getattr(delta, "content", None) if delta is not None else None
            if isinstance(piece, str) and piece:
                accumulated += piece
            fr = getattr(chunk.choices[0], "finish_reason", None)
            if fr is not None:
                finish_reason = fr or "stop"
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
        if self._router is not None:
            try:
                deployment_names = [d for d in self._router.get_model_names()]  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - router API variance
                deployment_names = [self.model]
            return [
                ModelInfo(id=name, provider=self.provider_name, metadata={"tenant": self.tenant})
                for name in deployment_names
            ]
        return [ModelInfo(id=self.model, provider=self.provider_name, metadata={"tenant": self.tenant})]
