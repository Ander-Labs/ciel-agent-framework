"""Fase 9 — built-in tools dispatch + `ciel init` scaffold (formal tests).

Offline-safe. No network; http_get uses an injected mock client.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ciel.cli.scaffold import scaffold_project
from ciel.runtime.tools import (
    DefaultToolDispatcher,
    Tool,
    ToolProvider,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


class _StubProvider(ToolProvider):
    def __init__(self, registry: ToolRegistry, require_tenant: bool = False):
        self.registry = registry
        self.require_tenant_on_execution = require_tenant

    async def tool_specs(self, tenant_id, toolset):
        return tuple(self.registry._toolsets.get(toolset, _empty()).tools)

    async def execute(self, *, tenant_id, toolset, name, arguments, tool_call_id):
        tool = self.registry.get_tool(toolset, name, tenant_id)
        if tool is None:
            return ToolResult(id=tool_call_id, name=name, error="not found")
        return tool.callable_(arguments, tool_call_id=tool_call_id, tenant_id=tenant_id)


def _empty():
    from ciel.runtime.tools import ToolsetSchema
    return ToolsetSchema(name="empty", description="")


def _make_echo():
    registry = ToolRegistry(default_toolset="default")
    registry.register_tool(
        "default",
        Tool(spec=ToolSpec(name="echo", description="echo", parameters={"text": {"type": "string"}}),
             callable_=_echo),
    )
    dispatcher = DefaultToolDispatcher(provider=_StubProvider(registry), default_toolset="default")
    return dispatcher


def _echo(arguments, *, tool_call_id="", tenant_id=None):
    return ToolResult(id=tool_call_id, name="echo", output={"echo": str(arguments.get("text", ""))})


@pytest.mark.asyncio
async def test_dispatch_echo_via_dispatcher():
    dispatcher = _make_echo()
    result = await dispatcher.dispatch(name="echo", arguments={"text": "hi"}, tool_call_id="1")
    assert result.output == {"echo": "hi"}


@pytest.mark.asyncio
async def test_dispatch_all_multiple_calls():
    dispatcher = _make_echo()
    results = await dispatcher.dispatch_all(
        calls=[{"name": "echo", "arguments": {"text": "a"}, "id": "1"},
               {"name": "echo", "arguments": {"text": "b"}, "id": "2"}]
    )
    assert [r.output["echo"] for r in results] == ["a", "b"]


@pytest.mark.asyncio
async def test_builtin_http_get_with_mock_client():
    from ciel.runtime.tools_builtins import register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)

    class _Resp:
        status_code = 200
        text = "<html>ok</html>"

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url):
            return _Resp()

    tool = registry.get_tool("builtins", "http_get")
    res = await tool.callable_({"url": "http://x"}, tool_call_id="1", client=_Client())
    assert res.output["status"] == 200
    assert "ok" in res.output["body"]


def test_scaffold_creates_project_files(tmp_path: Path):
    created = scaffold_project(tmp_path / "demo")
    rels = set(created)
    assert "pyproject.toml" in rels
    assert any(f.endswith("_agent.py") for f in rels)
    assert "ciel.yaml" in rels
    # idempotent: second run without force adds nothing new
    again = scaffold_project(tmp_path / "demo")
    assert again == []


def test_scaffold_generated_agent_runs_offline(tmp_path: Path):
    target = tmp_path / "demo"
    scaffold_project(target)
    agent = next(target.glob("*_agent.py"))
    import subprocess, sys
    proc = subprocess.run(
        [sys.executable, str(agent)],
        capture_output=True, text=True, timeout=120,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "echo:" in proc.stdout
