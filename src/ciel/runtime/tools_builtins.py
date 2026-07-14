"""Built-in tools shipped with Ciel.

All tools are defined as ``ToolSpec`` + callable and registered into the
``builtins`` toolset by ``register_builtin_tools``. Network/sandbox tools are
safe to import offline; their side effects only happen at execution time and
can be sandboxed via ``ciel.sandbox.SandboxContext``.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

import httpx

from ciel.runtime.tools import Tool, ToolResult, ToolSpec, ToolsetSchema
from ciel.sandbox import SandboxContext, SandboxPolicy


def _echo(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
    text = str(arguments.get("text", ""))
    return ToolResult(id=tool_call_id, name="echo", output={"echo": text})


def _datetime(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
    fmt = str(arguments.get("format", "%Y-%m-%dT%H:%M:%SZ"))
    now = datetime.datetime.now(datetime.timezone.utc).strftime(fmt)
    return ToolResult(id=tool_call_id, name="datetime", output={"now": now})


async def _http_get(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> ToolResult:
    url = str(arguments.get("url", ""))
    if not url:
        return ToolResult(id=tool_call_id, name="http_get", error="missing 'url'")
    ctx_client = client or httpx.AsyncClient(timeout=float(arguments.get("timeout", 30.0)))
    own = client is None
    try:
        resp = await ctx_client.get(url)
        body = resp.text
        return ToolResult(id=tool_call_id, name="http_get", output={"status": resp.status_code, "body": body[:4000]})
    except Exception as exc:  # pragma: no cover - network path
        return ToolResult(id=tool_call_id, name="http_get", error=f"request failed: {exc}")
    finally:
        if own:
            await ctx_client.aclose()


def _file_read(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
    policy = SandboxContext(policy=SandboxPolicy(allow_file_read=True))
    try:
        content = policy.read_file(str(arguments.get("path", "")))
        return ToolResult(id=tool_call_id, name="file_read", output={"content": content})
    except Exception as exc:
        return ToolResult(id=tool_call_id, name="file_read", error=str(exc))


def _shell(arguments: Dict[str, Any], *, tool_call_id: str = "", tenant_id: Optional[str] = None) -> ToolResult:
    policy = SandboxContext(policy=SandboxPolicy(allow_terminal=False))
    try:
        out = policy.execute(str(arguments.get("command", "")))
        return ToolResult(id=tool_call_id, name="shell", output={"output": out})
    except Exception as exc:
        return ToolResult(id=tool_call_id, name="shell", error=str(exc))


ECHO_TOOL = Tool(
    spec=ToolSpec(name="echo", description="Echo back the provided text.", parameters={"text": {"type": "string"}}),
    callable_=_echo,
)
DATETIME_TOOL = Tool(
    spec=ToolSpec(name="datetime", description="Return current UTC time.", parameters={"format": {"type": "string"}}),
    callable_=_datetime,
)
HTTP_GET_TOOL = Tool(
    spec=ToolSpec(name="http_get", description="GET a URL (requires network).", parameters={"url": {"type": "string"}, "timeout": {"type": "number"}}),
    callable_=_http_get,
)
FILE_READ_TOOL = Tool(
    spec=ToolSpec(name="file_read", description="Read a local file (sandboxed).", parameters={"path": {"type": "string"}}),
    callable_=_file_read,
)
SHELL_TOOL = Tool(
    spec=ToolSpec(name="shell", description="Run a shell command (disabled by default policy).", parameters={"command": {"type": "string"}}),
    callable_=_shell,
)

BUILTIN_TOOLS: tuple[Tool, ...] = (
    ECHO_TOOL,
    DATETIME_TOOL,
    HTTP_GET_TOOL,
    FILE_READ_TOOL,
    SHELL_TOOL,
)

BUILTIN_TOOLSET = ToolsetSchema(
    name="builtins",
    description="Ciel built-in tools (echo, datetime, http_get, file_read, shell).",
    tools=tuple(t.spec for t in BUILTIN_TOOLS),
)


def register_builtin_tools(registry) -> None:
    """Register all built-in tools into a ``ToolRegistry`` instance."""
    for tool in BUILTIN_TOOLS:
        registry.register_tool(BUILTIN_TOOLSET.name, tool)
