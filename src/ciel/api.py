"""Ciel high-level public API (Developer Experience layer).

This module is a thin, ergonomic facade built *on top of* the existing runtime
(``ciel.runtime``) and providers (``ciel.providers``). It does not replace the
low-level contracts — it wires them for you so the common case is a few lines:

    import ciel

    @ciel.tool
    def add(a: int, b: int) -> int:
        "Suma dos enteros."
        return a + b

    agent = ciel.Agent(provider=my_provider, tools=[add])
    resp = agent.run("Cuánto es 2 + 3?")
    print(resp.text)

Design goals:
  * ``@ciel.tool`` infers the JSON schema from type hints + docstring (Pydantic v2).
  * ``ciel.Agent`` encapsulates provider + registry + dispatcher + runtime.
  * ``ciel.Context`` injects tenant/session/user into tools that declare it.
  * ``ciel.AgentResponse`` exposes ``.text`` instead of navigating nested objects.

Multitenancy and traceability are preserved: ``tenant_id`` flows from
``Agent.run(..., tenant_id=...)`` down to the runtime (which normalises
``tenant_id=None`` to a stable sentinel) and to every tool via ``Context``.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, get_type_hints

from pydantic import create_model

from ciel.providers import ChatProvider
from ciel.runtime import (
    ChatMessage,
    ChatRequest,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolRegistry,
)
from ciel.runtime.tools import Tool, ToolResult, ToolSpec

__all__ = [
    "Context",
    "ToolFunction",
    "tool",
    "AgentResponse",
    "Agent",
]


# ---------------------------------------------------------------------------
# Context — dependency injection for tools
# ---------------------------------------------------------------------------
@dataclass
class Context:
    """Execution context injected into tools that declare a ``Context`` parameter.

    A tool can opt in to receive the context by annotating one of its
    parameters with :class:`Context`::

        @ciel.tool
        def whoami(ctx: ciel.Context) -> str:
            return f"tenant={ctx.tenant_id}"

    The parameter is excluded from the generated JSON schema (the model never
    sees it); Ciel fills it in at execution time.
    """

    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# @ciel.tool — schema inference from type hints + docstring
# ---------------------------------------------------------------------------
_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


class ToolFunction:
    """Callable wrapper produced by :func:`tool`.

    Wraps the user's function, keeps it callable as normal Python, and exposes
    the Ciel :class:`~ciel.runtime.tools.Tool` (with inferred ``ToolSpec`` and a
    runtime-compatible ``callable_``) via :pyattr:`as_tool`.
    """

    def __init__(self, fn: Callable[..., Any], *, name: str, description: str, tool: Tool) -> None:
        self._fn = fn
        self.name = name
        self.description = description
        self.as_tool = tool
        # Preserve dunders so the wrapper still looks like the original function.
        self.__name__ = getattr(fn, "__name__", name)
        self.__doc__ = fn.__doc__
        self.__wrapped__ = fn

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._fn(*args, **kwargs)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<ciel.tool {self.name!r}>"


def _context_param_name(fn: Callable[..., Any], hints: Dict[str, Any]) -> Optional[str]:
    """Return the name of the parameter annotated with :class:`Context`, if any."""
    for pname, ptype in hints.items():
        if pname == "return":
            continue
        if ptype is Context:
            return pname
    return None


def _build_schema(fn: Callable[..., Any], skip: Sequence[str]) -> Dict[str, Any]:
    """Infer a JSON schema for ``fn`` from its signature using Pydantic v2.

    Parameters listed in ``skip`` (e.g. the injected Context param) are excluded.
    Handles complex hints (List, Dict, Optional, Union) through Pydantic.
    """
    try:
        hints = get_type_hints(fn)
    except Exception:  # pragma: no cover - exotic annotations
        hints = getattr(fn, "__annotations__", {}) or {}
    sig = inspect.signature(fn)

    fields: Dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname in skip:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, Any)
        if annotation is inspect.Parameter.empty:
            annotation = Any
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[pname] = (annotation, default)

    if not fields:
        return {"type": "object", "properties": {}}

    model = create_model(f"{getattr(fn, '__name__', 'tool')}__args", **fields)  # type: ignore[call-overload]
    schema = model.model_json_schema()
    # Normalise: pydantic emits "title"/"$defs" we don't need at top level.
    schema.pop("title", None)
    return schema


def tool(
    fn: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Union[ToolFunction, Callable[[Callable[..., Any]], ToolFunction]]:
    """Decorator that turns a plain Python function into a Ciel tool.

    The JSON schema is inferred from the function's type hints, and the tool
    description defaults to the function's docstring. A parameter annotated with
    :class:`Context` is injected at runtime and excluded from the schema.

    Usage::

        @ciel.tool
        def add(a: int, b: int) -> int:
            "Suma dos enteros."
            return a + b

        @ciel.tool(name="buscar", description="Busca un cliente por id.")
        def find(customer_id: str, ctx: ciel.Context) -> dict:
            ...
    """

    def _decorate(func: Callable[..., Any]) -> ToolFunction:
        tool_name = name or func.__name__
        tool_desc = description or (inspect.getdoc(func) or "").strip() or tool_name

        try:
            hints = get_type_hints(func)
        except Exception:  # pragma: no cover
            hints = getattr(func, "__annotations__", {}) or {}
        ctx_param = _context_param_name(func, hints)
        skip = [ctx_param] if ctx_param else []
        parameters = _build_schema(func, skip=skip)

        spec = ToolSpec(name=tool_name, description=tool_desc, parameters=parameters)

        def _runtime_callable(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
            kwargs = dict(arguments or {})
            if ctx_param:
                kwargs[ctx_param] = Context(tenant_id=tenant_id, tool_call_id=tool_call_id)
            output = func(**kwargs)
            if isinstance(output, ToolResult):
                return output
            return ToolResult(id=tool_call_id, name=tool_name, output=output, metadata={"tenant_id": tenant_id})

        async def _async_runtime_callable(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
            kwargs = dict(arguments or {})
            if ctx_param:
                kwargs[ctx_param] = Context(tenant_id=tenant_id, tool_call_id=tool_call_id)
            output = await func(**kwargs)
            if isinstance(output, ToolResult):
                return output
            return ToolResult(id=tool_call_id, name=tool_name, output=output, metadata={"tenant_id": tenant_id})

        runtime_callable = _async_runtime_callable if inspect.iscoroutinefunction(func) else _runtime_callable

        ciel_tool = Tool(spec=spec, callable_=runtime_callable)
        return ToolFunction(func, name=tool_name, description=tool_desc, tool=ciel_tool)

    if fn is not None:
        return _decorate(fn)
    return _decorate


# ---------------------------------------------------------------------------
# AgentResponse — simplified result
# ---------------------------------------------------------------------------
@dataclass
class AgentResponse:
    """Ergonomic wrapper over the runtime's :class:`AgentRuntimeResult`.

    Access the final assistant text with :pyattr:`text`; the executed tool
    results with :pyattr:`tool_results`; and the raw runtime result with
    :pyattr:`raw` when you need full detail.
    """

    raw: Any

    @property
    def text(self) -> str:
        """The final assistant message content (empty string if none)."""
        try:
            return self.raw.response.choice.message.content or ""
        except AttributeError:  # pragma: no cover - defensive
            return ""

    @property
    def finish_reason(self) -> str:
        try:
            return self.raw.response.choice.finish_reason
        except AttributeError:  # pragma: no cover
            return "stop"

    @property
    def tool_results(self) -> List[ToolResult]:
        """Flat list of every tool result executed during the loop."""
        results: List[ToolResult] = []
        for turn in getattr(self.raw, "loop_results", ()) or ():
            results.extend(turn.tool_results)
        return results

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """Raw tool calls the model requested (name + arguments)."""
        meta = getattr(self.raw.response, "metadata", {}) or {}
        calls = meta.get("tool_calls")
        if isinstance(calls, list):
            return calls
        msg_calls = getattr(self.raw.response.choice.message, "tool_calls", None)
        return msg_calls if isinstance(msg_calls, list) else []

    @property
    def messages(self) -> Sequence[ChatMessage]:
        for turn in getattr(self.raw, "loop_results", ()) or ():
            return turn.messages
        return (self.raw.response.choice.message,)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.text


# ---------------------------------------------------------------------------
# Agent — high-level entry point
# ---------------------------------------------------------------------------
class Agent:
    """High-level agent that wires provider + tools + runtime for you.

    Example::

        agent = ciel.Agent(provider=my_provider, tools=[add], toolset="demo")
        resp = agent.run("Suma 2 + 3", tenant_id="acme")
        print(resp.text)

    Args:
        provider: A :class:`~ciel.providers.ChatProvider` instance. Required for
            actually running (offline stubs or real OpenAI/Anthropic/Gemini).
        tools: Iterable of ``@ciel.tool`` functions (or raw ``Tool`` objects).
        model: Optional model id passed to the provider on each request.
        toolset: Logical toolset name (default ``"default"``).
        instructions: Optional system prompt prepended to every run.
        tenant_id: Default tenant used when a run does not override it.
        require_tenant: If True, tool execution requires a tenant_id.
        name: Agent name used in audit events.
        approval_policy: Optional approval policy (HITL) forwarded to the runtime.
        temperature / max_tokens: Optional generation defaults.
    """

    def __init__(
        self,
        *,
        provider: Optional[ChatProvider] = None,
        tools: Optional[Sequence[Any]] = None,
        model: Optional[str] = None,
        toolset: str = "default",
        instructions: Optional[str] = None,
        tenant_id: Optional[str] = None,
        require_tenant: bool = False,
        name: str = "ciel-agent",
        approval_policy: Optional[Any] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.toolset = toolset
        self.instructions = instructions
        self.tenant_id = tenant_id
        self.name = name
        self.temperature = temperature
        self.max_tokens = max_tokens

        registry = ToolRegistry(default_toolset=toolset)
        for t in tools or []:
            ciel_tool = t.as_tool if isinstance(t, ToolFunction) else t
            if not isinstance(ciel_tool, Tool):
                raise TypeError(
                    f"tools must be @ciel.tool functions or Tool objects, got {type(t).__name__}"
                )
            registry.register_tool(toolset, ciel_tool)
        self.registry = registry

        self._tool_specs: List[ToolSpec] = [
            registry.get_tool(toolset=toolset, name=n).spec  # type: ignore[union-attr]
            for n in registry.tool_names(toolset)
        ]

        tool_provider = ToolProvider(registry=registry, require_tenant_on_execution=require_tenant)
        dispatcher = DefaultToolDispatcher(provider=tool_provider, default_toolset=toolset)
        self.runtime = DefaultAgentRuntime(
            provider=provider,
            dispatcher=dispatcher,
            agent=name,
            approval_policy=approval_policy,
        )

    def _build_request(self, prompt: str) -> ChatRequest:
        messages: List[ChatMessage] = []
        if self.instructions:
            messages.append(ChatMessage(role="system", content=self.instructions))
        messages.append(ChatMessage(role="user", content=prompt))
        return ChatRequest(
            messages=tuple(messages),
            tools=tuple(self._tool_specs),
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    async def arun(
        self,
        prompt: str,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 32,
    ) -> AgentResponse:
        """Run the agent asynchronously and return an :class:`AgentResponse`."""
        if self.provider is None:
            raise ValueError(
                "Agent has no provider. Pass provider=<ChatProvider> to Agent(...)."
            )
        # Resolve tenant: explicit arg > agent default > "default" sentinel.
        # The runtime's audit layer requires a tenant_id (multitenancy is
        # native); the facade supplies a safe default so the common case
        # (agent.run("hola")) works without forcing the user to pass one.
        effective_tenant = (
            tenant_id if tenant_id is not None else (self.tenant_id or "default")
        )
        result = await self.runtime.run_agent_loop(
            request=self._build_request(prompt),
            tenant_id=effective_tenant,
            toolset=self.toolset,
            limit=limit,
        )
        return AgentResponse(raw=result)

    def run(
        self,
        prompt: str,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 32,
    ) -> AgentResponse:
        """Run the agent synchronously (convenience wrapper over :meth:`arun`).

        Raises ``RuntimeError`` if called from inside a running event loop; use
        :meth:`arun` in async code.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(prompt, tenant_id=tenant_id, limit=limit))
        raise RuntimeError(
            "Agent.run() cannot be called from a running event loop; use 'await agent.arun(...)' instead."
        )
