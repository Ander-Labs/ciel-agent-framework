"""ACP server and message contract for IDE integrations.

ACP (Agent Communication Protocol) provides:
- A typed message envelope (`ACPMessage`) for IDE<->agent communication.
- An `ACPServer` with per-event handler registration and tenant isolation.
- A `create_app` factory that returns a FastAPI app with ``/health``,
  ``/v1/chat``, ``/v1/acp`` (webhook) and ``/v1/tools`` endpoints.

The server is intentionally thin: the heavy lifting (tool loop, audit,
multi-tenancy) is delegated to the existing ``DefaultAgentRuntime``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from ciel.providers import OpenAICompatibleProvider
from ciel.runtime import (
    ChatMessage,
    ChatRequest,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    StaticToolProvider,
    ToolSpec,
)

__all__ = [
    "ACPMessage",
    "ACPServer",
    "AskRequest",
    "AskResponse",
    "ToolResultPayload",
    "create_app",
]


# ---------------------------------------------------------------------------
# Message contract
# ---------------------------------------------------------------------------


@dataclass
class ACPMessage:
    """Typed envelope for ACP events.

    ``type`` identifies the event kind (e.g. ``"task.start"``).
    ``data`` carries the opaque payload; ``id`` and ``session_id`` are
    optional correlation identifiers.
    """

    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    session_id: Optional[str] = None


# Type alias for handler callables: sync or async, receiving ACPMessage.
ACPHandler = Callable[[ACPMessage], "Any | Awaitable[Any]"]


class ACPServer:
    """Minimal ACP server with event-handler registration.

    The server is tenant-aware: handlers receive the full `ACPMessage`
    and are responsible for respecting tenant isolation if needed.
    """

    def __init__(
        self,
        *,
        route_path: str = "/v1/acp",
        tenant_id: Optional[str] = None,
    ) -> None:
        self.route_path = route_path
        self.tenant_id = tenant_id
        self.event_handlers: Dict[str, ACPHandler] = {}

    def on(self, event_type: str, handler: ACPHandler) -> None:
        """Register a handler for an event type."""
        self.event_handlers[event_type] = handler

    def off(self, event_type: str) -> None:
        self.event_handlers.pop(event_type, None)

    async def handle(self, message: ACPMessage) -> Any:
        """Dispatch ``message`` to its registered handler.

        Returns ``None`` if no handler is registered for ``message.type``.
        """
        handler = self.event_handlers.get(message.type)
        if handler is None:
            return None
        result = handler(message)
        import inspect

        if inspect.isawaitable(result):
            result = await result
        return result


# ---------------------------------------------------------------------------
# Request / response models for the FastAPI surface
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    toolset: str = "demo"
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None


class AskResponse(BaseModel):
    text: str
    session_id: Optional[str] = None


class ToolResultPayload(BaseModel):
    ok: bool
    output: Any = None
    error: Optional[str] = None


class ACPWebhookPayload(BaseModel):
    type: str
    data: Dict[str, Any] = {}
    id: Optional[str] = None
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Runtime factory
# ---------------------------------------------------------------------------


def _build_runtime(
    base_url: str,
    api_key: Optional[str],
    default_model: Optional[str],
) -> DefaultAgentRuntime:
    provider = OpenAICompatibleProvider(
        base_url=base_url, api_key=api_key, default_model=default_model
    )
    toolset = "demo"
    tools = tuple(
        ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            metadata={},
        )
        for name, description, parameters in [
            (
                "echo",
                "Devuelve el texto recibido.",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            ),
            (
                "uppercase",
                "Convierte el texto recibido a mayusculas.",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            ),
            (
                "add",
                "Suma dos numeros.",
                {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            ),
        ]
    )
    provider_tools = {toolset: tools}
    tool_provider = StaticToolProvider(tools=provider_tools)
    dispatcher = DefaultToolDispatcher(provider=tool_provider, default_toolset=toolset)
    return DefaultAgentRuntime(provider=provider, dispatcher=dispatcher)


# ---------------------------------------------------------------------------
# FastAPI factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    base_url: str = "http://localhost:11434/v1",
    api_key: Optional[str] = None,
    default_model: Optional[str] = "llama3",
    acp_server: Optional[ACPServer] = None,
) -> FastAPI:
    """Build the Ciel ACP FastAPI application.

    Parameters
    ----------
    base_url, api_key, default_model:
        Configuration for the backing ``OpenAICompatibleProvider``.
    acp_server:
        Optional pre-configured :class:`ACPServer`. If omitted, a bare
        server is created so callers can register handlers later via
        ``app.state.acp``.
    """
    app = FastAPI(title="Ciel ACP", version="0.1.0")
    app.state.runtime = _build_runtime(
        base_url=base_url, api_key=api_key, default_model=default_model
    )
    app.state.acp = acp_server or ACPServer()

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok", "service": "ciel-acp", "version": "0.1.0"}

    @app.post("/v1/chat", response_model=AskResponse)
    async def chat(payload: AskRequest) -> AskResponse:
        request = ChatRequest(
            messages=(ChatMessage(role="user", content=payload.prompt),),
            model=payload.model,
            extra={"session_id": payload.session_id},
        )
        result = await app.state.runtime.run_agent_loop(
            request=request,
            tenant_id=payload.tenant_id,
            toolset=payload.toolset,
        )
        message = result.response.choice.message
        return AskResponse(
            text=message.content or "",
            session_id=result.metadata.get("session_id"),
        )

    @app.post("/v1/tools/{toolset}/{name}", response_model=ToolResultPayload)
    async def invoke_tool(
        toolset: str, name: str, arguments: Dict[str, Any]
    ) -> ToolResultPayload:
        provider_instance = app.state.runtime.dispatcher.provider
        tool_result = await provider_instance.execute(
            toolset=toolset,
            name=name,
            arguments=arguments,
            tool_call_id=f"http-{toolset}-{name}",
        )
        return ToolResultPayload(
            ok=tool_result.error is None,
            output=tool_result.output,
            error=tool_result.error,
        )

    @app.post(app.state.acp.route_path)
    async def acp_webhook(payload: ACPWebhookPayload) -> Dict[str, Any]:
        message = ACPMessage(
            type=payload.type,
            data=dict(payload.data),
            id=payload.id,
            session_id=payload.session_id,
        )
        response: Dict[str, Any] = {"type": message.type, "status": "accepted"}
        if message.id is not None:
            response["id"] = message.id
        if message.session_id is not None:
            response["session_id"] = message.session_id
        try:
            result = await app.state.acp.handle(message)
        except Exception as exc:  # pragma: no cover - defensive path
            response["status"] = "error"
            response["error"] = str(exc)
            return response
        response["result"] = result
        return response

    return app


def _generate_id() -> str:
    return str(uuid.uuid4())
