from __future__ import annotations

from typing import Any

from ciel.providers import (
    AnthropicProvider,
    ModelInfo,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderFactory,
)
from ciel.runtime import ChatMessage, ChatRequest


def test_anthropic_provider_returns_default_model() -> None:
    provider = AnthropicProvider(api_key="test", default_model="custom-model")

    models = _run_sync(provider.models())

    assert models == [
        ModelInfo(
            id="custom-model",
            provider="anthropic",
            capabilities=(),
            context_window=None,
            metadata={"tenant": None},
        )
    ]


def test_factory_returns_openai_like_provider() -> None:
    config = ProviderConfig(
        name="local-llm",
        base_url="https://local.llm/v1",
        api_key="test",
        default_model="local-model",
    )

    provider = ProviderFactory.from_config(config)

    assert provider.provider_name == "openai_compat"
    assert provider.default_model == "local-model"
    assert provider.base_url == "https://local.llm/v1"
    assert provider.tenant is None


def test_openai_complete_serializes_chat_messages() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://local.example/openai/v1",
        api_key="test",
        default_model="test-model",
    )
    request = ChatRequest(
        messages=[_chat("user", "ping"), _chat("assistant", "pong", name="custom")],
        model="test-model",
    )

    serialized = [_serialize(m) for m in request.messages]

    assert serialized == [
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": "pong", "name": "custom"},
    ]


def _run_sync(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _serialize(message: ChatMessage) -> dict[str, str]:
    payload: dict[str, str] = {"role": message.role, "content": message.content}
    if message.name is not None:
        payload["name"] = message.name
    return payload


def _chat(role: str, content: str, name: str | None = None) -> ChatMessage:
    return ChatMessage(role=role, content=content, name=name)
