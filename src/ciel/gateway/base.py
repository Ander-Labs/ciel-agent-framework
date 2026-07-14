from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ciel import __version__
from ciel.orchestration.board import KanbanBoard
from ciel.providers import ProviderRegistry
from ciel.runtime import (
    AgentRuntimeResult,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolResult,
)

logger = logging.getLogger(__name__)


# --- pydantic request/response models ---------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ProviderInfo(BaseModel):
    name: str
    provider_name: Optional[str] = None


class InfoResponse(BaseModel):
    version: str
    providers: List[ProviderInfo]
    default_tenant: Optional[str] = None


class AgentRunRequest(BaseModel):
    prompt: str = Field(..., description="User prompt text.")
    model: Optional[str] = Field(None, description="Model id to use for completion.")
    toolset: Optional[str] = Field(None, description="Toolset name for tool dispatch.")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier propagated to runtime.")
    session_id: Optional[str] = Field(None, description="Optional session id for tracing.")
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ToolResultPayload(BaseModel):
    id: Optional[str] = None
    name: str
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    text: str
    session_id: Optional[str] = None
    tool_results: List[ToolResultPayload]


class ToolInvokeRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    tool_call_id: Optional[str] = None
    tenant_id: Optional[str] = None


class ToolInvokeResponse(BaseModel):
    id: Optional[str] = None
    name: str
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BoardTaskPayload(BaseModel):
    id: str
    title: str
    status: str = "todo"
    assignee: Optional[str] = None
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BoardListResponse(BaseModel):
    tasks: List[BoardTaskPayload]


# --- helpers ----------------------------------------------------------------

def _tool_result_to_payload(result: ToolResult) -> ToolResultPayload:
    return ToolResultPayload(
        id=getattr(result, "id", None),
        name=getattr(result, "name", ""),
        output=getattr(result, "output", None),
        error=getattr(result, "error", None),
        metadata=dict(getattr(result, "metadata", {}) or {}),
    )


def _serialize_chat_response(result: AgentRuntimeResult) -> AgentRunResponse:
    response: ChatResponse = result.response
    text = getattr(response.choice.message, "content", "") or ""
    session_id = result.metadata.get("session_id")
    tool_results: List[ToolResultPayload] = []
    for turn in result.loop_results:
        for tr in turn.tool_results:
            tool_results.append(_tool_result_to_payload(tr))
    return AgentRunResponse(text=text, session_id=session_id, tool_results=tool_results)


def _list_board_tasks(board: KanbanBoard, tenant_id: Optional[str]) -> List[BoardTaskPayload]:
    tasks = board.list_tasks(tenant_id=tenant_id)
    out: List[BoardTaskPayload] = []
    for task in tasks:
        out.append(
            BoardTaskPayload(
                id=task.id,
                title=task.title,
                status=task.status,
                assignee=task.assignee,
                tenant_id=task.tenant_id,
                metadata=dict(task.metadata or {}),
            )
        )
    return out


# --- factory ----------------------------------------------------------------

def create_control_app(
    *,
    runtime: DefaultAgentRuntime,
    registry: Optional[ProviderRegistry] = None,
    audit_sink: Any = None,
    tenant_id: Optional[str] = None,
    api_key: Optional[str] = None,
    board_db_path: Optional[str] = None,
) -> FastAPI:
    """Build a FastAPI control plane for the Ciel agent runtime.

    Parameters
    ----------
    runtime:
        A :class:`ciel.runtime.DefaultAgentRuntime` used to run agent loops and
        dispatch tools. Tool dispatch goes through ``runtime.dispatcher``.
        El endpoint ``POST /v1/agent/run/stream`` usa
        ``runtime.stream_tokens`` para emitir Server-Sent Events (SSE) con los
        fragmentos incrementales del assistant y cierra con ``data: [DONE]``.
    registry:
        Optional :class:`ciel.providers.ProviderRegistry` surfaced via the
        ``GET /info`` endpoint. If omitted, an empty provider list is reported.
    audit_sink:
        Optional audit sink retained for observability hooks. Not directly
        invoked here — the runtime already emits audit events.
    tenant_id:
        Default tenant propagated to the runtime when a request does not
        provide its own ``tenant_id``.
    api_key:
        Optional transport API key. When ``None`` (the default), the
        ``CIEL_API_KEY`` environment variable is consulted. If a key is
        configured (explicitly or via env), protected routes require a valid
        key via ``Authorization: Bearer *** or ``X-API-Key``; otherwise
        the dependency is a no-op (open mode).
    board_db_path:
        Optional path to a SQLite database for the kanban board. When set (o
        bien vía la variable de entorno ``CIEL_BOARD_DB``), el board se monta
        sobre SQLite para que ``/v1/board/list`` vea las tareas creadas por el
        CLI y viceversa. Si no se configura ninguna ruta, el board queda en
        memoria (comportamiento legacy, útil para smoke tests/offline).
    """
    from ciel.gateway.auth import Depends, make_auth_dependency

    api_key_guard = Depends(make_auth_dependency(expected_key=api_key))

    app = FastAPI(
        title="Ciel Control Gateway",
        version=__version__,
        description="HTTP control plane for the Ciel agent runtime.",
    )
    # Attach references for tests / introspection.
    app.state.runtime = runtime
    app.state.registry = registry
    app.state.audit_sink = audit_sink
    app.state.default_tenant_id = tenant_id

    # Resolve a live board instance if orchestration is available.
    # Si se pasa board_db_path o existe CIEL_BOARD_DB, el board se monta sobre
    # SQLite para compartir estado con el CLI; en caso contrario queda en
    # memoria (fallback para smoke tests/offline).
    board: Optional[KanbanBoard] = None
    resolved_board_db = board_db_path or os.environ.get("CIEL_BOARD_DB")
    try:
        board = KanbanBoard(path=resolved_board_db)  # None => en memoria.
    except Exception:  # pragma: no cover - defensive guard
        board = None
    app.state.board = board

    def _resolve_tenant(request_tenant: Optional[str]) -> Optional[str]:
        return request_tenant or tenant_id

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @app.get("/info", response_model=InfoResponse, tags=["meta"])
    async def info() -> InfoResponse:
        providers: List[ProviderInfo] = []
        if registry is not None:
            for name in registry.available():
                provider_name: Optional[str] = None
                try:
                    provider = registry.get(name)
                    provider_name = getattr(provider, "provider_name", None)
                except Exception:
                    provider_name = None
                providers.append(ProviderInfo(name=name, provider_name=provider_name))
        return InfoResponse(
            version=__version__,
            providers=providers,
            default_tenant=tenant_id,
        )

    @app.post(
        "/v1/agent/run",
        response_model=AgentRunResponse,
        tags=["agent"],
        dependencies=[api_key_guard],
    )
    async def agent_run(body: AgentRunRequest) -> AgentRunResponse:
        effective_tenant = _resolve_tenant(body.tenant_id)
        if effective_tenant is None:
            raise HTTPException(
                status_code=400,
                detail="tenant_id is required (multi-tenancy is enforced). "
                "Provide it in the request or configure a default tenant in the gateway.",
            )
        session_id = body.session_id or str(uuid.uuid4())
        request = _build_chat_request(body, session_id, effective_tenant)
        try:
            result = await runtime.run_agent_loop(
                request=request,
                tenant_id=effective_tenant,
                toolset=body.toolset,
            )
        except Exception as exc:
            logger.exception("agent.run failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"agent loop failed: {exc}") from exc
        return _serialize_chat_response(result)

    def _build_chat_request(body: AgentRunRequest, session_id: str, effective_tenant: Optional[str]) -> ChatRequest:
        extra: Dict[str, Any] = dict(body.extra or {})
        extra.setdefault("session_id", session_id)
        if effective_tenant is not None:
            extra.setdefault("tenant_id", effective_tenant)
        return ChatRequest(
            messages=(ChatMessage(role="user", content=body.prompt),),
            tools=(),
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            extra=extra,
        )

    @app.post(
        "/v1/agent/run/stream",
        tags=["agent"],
        dependencies=[api_key_guard],
    )
    async def agent_run_stream(body: AgentRunRequest) -> StreamingResponse:
        """Stream the assistant completion as Server-Sent Events.

        Emite cada fragmento incremental del assistant como un evento SSE
        ``data: <token>`` y cierra la respuesta con ``data: [DONE]``.
        Reutiliza ``runtime.stream_tokens`` (que a su vez llama a
        ``provider.stream`` para hacer SSE real cuando el proveedor lo soporta).

        El ``tenant_id`` es obligatorio, igual que en ``/v1/agent/run``.
        """
        effective_tenant = _resolve_tenant(body.tenant_id)
        if effective_tenant is None:
            raise HTTPException(
                status_code=400,
                detail="tenant_id is required (multi-tenancy is enforced). "
                "Provide it in the request or configure a default tenant in the gateway.",
            )
        session_id = body.session_id or str(uuid.uuid4())

        async def _event_generator():
            try:
                request = _build_chat_request(body, session_id, effective_tenant)
                async for token in runtime.stream_tokens(
                    request=request,
                    tenant_id=effective_tenant,
                    toolset=body.toolset,
                ):
                    yield f"data: {token}\n\n"
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("agent.run.stream failed: %s", exc)
                yield f"data: [ERROR] {exc}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    @app.post(
        "/v1/tools/{toolset}/{name}",
        response_model=ToolInvokeResponse,
        tags=["tools"],
        dependencies=[api_key_guard],
    )
    async def tool_invoke(toolset: str, name: str, body: ToolInvokeRequest) -> ToolInvokeResponse:
        dispatcher: Optional[DefaultToolDispatcher] = getattr(runtime, "dispatcher", None)
        if dispatcher is None:
            raise HTTPException(status_code=500, detail="runtime has no tool dispatcher")
        effective_tenant = _resolve_tenant(body.tenant_id)
        if effective_tenant is None:
            raise HTTPException(
                status_code=400,
                detail="tenant_id is required to dispatch tools (multi-tenancy is enforced).",
            )
        tool_call_id = body.tool_call_id or str(uuid.uuid4())
        try:
            result = await dispatcher.dispatch(
                tenant_id=effective_tenant,
                toolset=toolset,
                name=name,
                arguments=dict(body.arguments or {}),
                tool_call_id=tool_call_id,
            )
        except Exception as exc:
            logger.exception("tool.invoke failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"tool dispatch failed: {exc}") from exc
        return ToolInvokeResponse(
            id=getattr(result, "id", None),
            name=getattr(result, "name", name),
            output=getattr(result, "output", None),
            error=getattr(result, "error", None),
            metadata=dict(getattr(result, "metadata", {}) or {}),
        )

    @app.get(
        "/v1/board/list",
        response_model=BoardListResponse,
        tags=["board"],
        dependencies=[api_key_guard],
    )
    async def board_list(tenant_id: Optional[str] = None) -> BoardListResponse:
        effective_tenant = _resolve_tenant(tenant_id)
        if board is None:
            return BoardListResponse(tasks=[])
        return BoardListResponse(tasks=_list_board_tasks(board, effective_tenant))

    return app


__all__ = ["create_control_app"]
