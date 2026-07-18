from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]
    strict: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    spec: ToolSpec
    callable_: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    required_tenant: bool = False


@dataclass
class ToolResult:
    id: str
    name: str
    output: Any = None
    error: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolProvider:
    """Contract: discover tools and execute tool calls."""

    async def tool_specs(self, tenant_id, toolset):
        raise NotImplementedError

    async def execute(self, *, tenant_id, toolset, name, arguments, tool_call_id):
        raise NotImplementedError


class StaticToolProvider(ToolProvider):
    def __init__(self, tools, *, require_tenant=False):
        registry = ToolRegistry(default_toolset="default")
        for toolset_name, values in tools.items():
            specs = tuple(values) if not isinstance(values, tuple) else values
            registry.register_toolset(
                ToolsetSchema(
                    name=toolset_name,
                    description="",
                    tools=specs,
                    require_tenant=require_tenant,
                )
            )
        self.registry = registry
        self.require_tenant = require_tenant

    async def tool_specs(self, tenant_id, toolset):
        return tuple(self.registry._toolsets.get(toolset, ToolsetSchema(name=toolset, description="")).tools)

    async def execute(self, *, toolset, name, arguments, tool_call_id, tenant_id=None):
        target_toolset = toolset or self.registry.default_toolset or "default"
        if self.require_tenant and not tenant_id:
            raise ValueError(f"tenant_id is required to execute tool '{name}'.")
        tool = self.registry.get_tool(toolset=target_toolset, name=name)
        if tool is None:
            return ToolResult(id=tool_call_id, name=name, error=f"tool not found: {target_toolset}.{name}", metadata={"tenant_id": tenant_id})
        try:
            result = tool.callable_(arguments, tool_call_id=tool_call_id, tenant_id=tenant_id)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — surface tool errors as ToolResult
            return ToolResult(id=tool_call_id, name=name, error=f"{type(exc).__name__}: {exc}", metadata={"tenant_id": tenant_id})
        if isinstance(result, ToolResult):
            return result
        return ToolResult(id=tool_call_id, name=name, output=result, metadata={"tenant_id": tenant_id})


class DefaultToolDispatcher:
    """Dispatch tool requests to a configured ToolProvider."""

    def __init__(self, provider: ToolProvider, default_toolset: Optional[str] = None) -> None:
        self.provider = provider
        self.default_toolset = default_toolset or getattr(provider.registry, "default_toolset", None) or "default"

    async def dispatch(
        self,
        *,
        toolset: Optional[str] = None,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
        tenant_id: Optional[str] = None,
    ) -> ToolResult:
        result = await self.provider.execute(
            toolset=toolset or self.default_toolset,
            name=name,
            arguments=arguments,
            tool_call_id=tool_call_id,
            tenant_id=tenant_id,
        )
        result.metadata.setdefault("tenant_id", tenant_id)
        return result

    async def dispatch_all(
        self,
        *,
        toolset: Optional[str] = None,
        calls: Sequence[Dict[str, Any]],
        base_tenant_id: Optional[str] = None,
    ) -> Sequence[ToolResult]:
        results = []
        for call in calls:
            call_tenant_id = call.get("metadata", {}).get("tenant_id") or base_tenant_id
            results.append(
                await self.dispatch(
                    toolset=toolset or self.default_toolset,
                    name=call["name"],
                    arguments=call.get("arguments", {}),
                    tool_call_id=call.get("id") or call.get("tool_call_id"),
                    tenant_id=call_tenant_id,
                )
            )
        return results


# A single content part is a dict, e.g. {"type": "text", "text": "..."} or
# {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}.
ContentPart = Dict[str, Any]

# Multimodal: content may be a plain string (legacy/most common) or a list of
# content parts (vision/audio/video). The ``str`` contract is fully preserved;
# passing a string keeps working unchanged everywhere.
ChatContent = "str | list[ContentPart]"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: ChatContent
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        """Extract plain text from content, tolerant to multimodal parts.

        - ``str`` content is returned verbatim.
        - ``list`` content concatenates the ``text`` of every part whose type
          is ``"text"`` but drops images/audio/video, so consumers (CLI,
          compression, ``AgentResponse.text``) see only readable text.
        """
        content = self.content
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)


@dataclass(frozen=True)
class ChatChoice:
    message: ChatMessage
    finish_reason: str
    usage: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatRequest:
    messages: Sequence[ChatMessage]
    tools: Sequence[ToolSpec] = ()
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    choice: ChatChoice
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelProvider:
    """Model/provider contract for completions."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream(self, request: ChatRequest) -> Sequence[ChatResponse]:
        raise NotImplementedError


@dataclass(frozen=True)
class ToolLoopResult:
    turn_id: str
    messages: Sequence[ChatMessage]
    tool_results: Sequence[ToolResult]
    finish_reason: str
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeResult:
    response: ChatResponse
    loop_results: Sequence[ToolLoopResult]
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    agent: str
    session_id: str
    tenant_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentRuntime:
    """Async runtime contract for tool-loop execution and streaming."""

    async def run_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AgentRuntimeResult:
        raise NotImplementedError

    async def stream_agent_loop(
        self,
        *,
        request: ChatRequest,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ):
        raise NotImplementedError


@dataclass
class ToolCallContext:
    tenant_id: Optional[str]
    toolset: str
    tool_name: str
    tool_call_id: str
    arguments: Dict[str, Any]

    def at(self, *, tenant_id: Optional[str]) -> ToolCallContext:
        return ToolCallContext(
            tenant_id=tenant_id,
            toolset=self.toolset,
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id,
            arguments=self.arguments,
        )


@dataclass
class ToolsetSchema:
    name: str
    description: str
    version: str = "1.0.0"
    tenants: Sequence[str] = ()
    default_tenant: Optional[str] = None
    require_tenant: bool = False
    tools: Sequence[ToolSpec] = ()

    def tenant_for(self, *, caller_tenant_id: Optional[str]) -> Optional[str]:
        if self.require_tenant and not caller_tenant_id:
            raise ValueError(f"Toolset '{self.name}' requires tenant_id; none was provided.")
        return caller_tenant_id or self.default_tenant

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "strict": tool.strict,
                    **( {"metadata": tool.metadata} if tool.metadata else {} ),
                }
                for tool in self.tools
            ],
        }
        if self.require_tenant:
            payload["require_tenant"] = True
        if self.tenants:
            payload["tenants"] = list(self.tenants)
        return payload


class TenantAwareToolProvider:
    """Tenant-aware provider contract."""

    async def tool_specs(self, tenant_id, toolset):
        raise NotImplementedError

    async def execute(self, *, context):
        raise NotImplementedError


class ToolExecutionContext:
    def __init__(self, *, tenant_id, toolset, name, tool_call_id, arguments):
        if not tenant_id:
            raise ValueError(f"tenant_id is required to execute tool '{name}' in toolset '{toolset}'.")
        self.context = ToolCallContext(
            tenant_id=tenant_id,
            toolset=toolset,
            tool_name=name,
            tool_call_id=tool_call_id,
            arguments=arguments,
        )

    @property
    def tenant_id(self) -> Optional[str]:
        return self.context.tenant_id

    @property
    def toolset(self) -> str:
        return self.context.toolset

    @property
    def name(self) -> str:
        return self.context.tool_name


class ToolRegistry:
    def __init__(self, *, default_toolset: Optional[str] = None) -> None:
        self._toolsets: Dict[str, ToolsetSchema] = {}
        self._tools: Dict[str, Dict[str, Tool]] = {}
        self._tenant_tools: Dict[str, Dict[str, Dict[str, Tool]]] = {}
        self.default_toolset = default_toolset

    def register_toolset(self, schema: ToolsetSchema) -> None:
        self._toolsets[schema.name] = schema
        self._tools.setdefault(schema.name, {})
        self._tenant_tools.setdefault(schema.name, {})
        for tool in schema.tools:
            self._tools[schema.name][tool.name] = Tool(spec=tool, required_tenant=schema.require_tenant)

    def register_tool(self, toolset, tool, *, tenant_id=None):
        if isinstance(toolset, ToolsetSchema):
            schema = toolset
            toolset = schema.name
            self._toolsets[schema.name] = schema
            self._tools.setdefault(schema.name, {})
            self._tenant_tools.setdefault(schema.name, {})
            for tool in schema.tools:
                self._tools[schema.name][tool.name] = Tool(spec=tool, required_tenant=schema.require_tenant)
            return
        schema = self._toolsets.get(toolset)
        require_tenant = schema.require_tenant if schema is not None else tool.required_tenant
        tool_obj = Tool(spec=tool.spec, callable_=tool.callable_, metadata=tool.metadata, required_tenant=tool.required_tenant or require_tenant)
        if schema is None:
            schema = ToolsetSchema(name=toolset, description="", require_tenant=require_tenant)
            self._toolsets[toolset] = schema
        self._tools.setdefault(toolset, {})
        self._tools[toolset][tool.spec.name] = tool_obj
        # Keep the schema's tool list in sync so get_toolset_schema/export_schema reflect registered tools.
        self._toolsets[toolset] = replace(schema, tools=tuple(t.spec for t in self._tools[toolset].values()))
        if tenant_id:
            self._tenant_tools.setdefault(toolset, {}).setdefault(tenant_id, {})[tool.spec.name] = tool_obj

    def get_toolset(self, name):
        return self._toolsets.get(name)

    def get_tool(self, toolset: str, name: str, tenant_id: Optional[str] = None):
        if tenant_id:
            tenant_tools = self._tenant_tools.get(toolset, {}).get(tenant_id)
            if tenant_tools is None:
                raise ValueError(f"tenant_id='{tenant_id}' has no mapped tools for toolset='{toolset}'")
            tool = tenant_tools.get(name)
            if tool is not None:
                return tool
        tools = self._tools.get(toolset)
        if not tools:
            return None
        return tools.get(name)

    def toolset_names(self) -> Sequence[str]:
        return tuple(self._toolsets.keys())

    def tool_names(self, toolset: str) -> Sequence[str]:
        return tuple(self._tools.get(toolset, {}).keys())

    def export_schema(self, toolset: str) -> Dict[str, Any]:
        schema = self._toolsets.get(toolset)
        if schema is None:
            raise KeyError(f"unknown toolset: {toolset}")
        return schema.to_json()

    async def lookup(self, *, tenant_id: Optional[str], toolset: str) -> Sequence[Tool]:
        schema = self._toolsets.get(toolset)
        if schema is None:
            return ()
        effective_tenant = schema.tenant_for(caller_tenant_id=tenant_id)
        if effective_tenant:
            tools = self._tenant_tools.get(toolset, {}).get(effective_tenant)
            if tools:
                return tuple(tools.values())
        return tuple(self._tools.get(toolset, {}).values())


__all__ = [
    "ToolSpec",
    "Tool",
    "ToolResult",
    "ToolProvider",
    "StaticToolProvider",
    "DefaultToolDispatcher",
    "ToolCallContext",
    "ToolsetSchema",
    "ToolExecutionContext",
    "ToolRegistry",
    "TenantAwareToolProvider",
    "ChatMessage",
    "ChatChoice",
    "ChatRequest",
    "ChatResponse",
    "ModelProvider",
    "ToolLoopResult",
    "AgentRuntimeResult",
    "AgentContext",
    "AgentRuntime",
]
