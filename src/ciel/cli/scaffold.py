"""Project scaffolding for ``ciel init``.

Generates a minimal, offline-runnable Ciel project: a pyproject with a
``ciel.plugins`` entry point example, a starter agent module and a ``ciel.yaml``.
Idempotent: refuses to overwrite existing files unless ``force=True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = "A Ciel Agent Framework project"
requires-python = ">=3.11"
dependencies = ["mana-ciel"]

[project.entry-points."ciel.plugins"]
# Register your own providers/tools/agents here, e.g.:
# my_provider = my_project.plugins:register_provider

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["{module}"]
"""

_AGENT = '''\
"""Starter Ciel agent (offline-safe).

Run with:  uv run python {module}.py
"""
from __future__ import annotations

from ciel.providers import OpenAICompatibleProvider
from ciel.runtime import (
    ChatMessage,
    ChatRequest,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolRegistry,
)
from ciel.runtime.tools import ToolSpec, Tool, ToolsetSchema


def _echo(arguments, *, tool_call_id="", tenant_id=None):
    from ciel.runtime.tools import ToolResult
    return ToolResult(id=tool_call_id, name="echo", output={"echo": str(arguments.get("text", ""))})


def build_runtime():
    # Offline echo provider; swap for OpenAICompatibleProvider(base_url=..., api_key=...) with a real key.
    registry = ToolRegistry(default_toolset="default")
    registry.register_tool(
        "default",
        Tool(spec=ToolSpec(name="echo", description="Echo text", parameters={"text": {"type": "string"}}), callable_=_echo),
    )
    dispatcher = DefaultToolDispatcher(
        provider=ToolProvider(registry=registry, require_tenant_on_execution=False),
        default_toolset="default",
    )
    return DefaultAgentRuntime(provider=_EchoProvider(), dispatcher=dispatcher)


class _EchoProvider:
    provider_name = "echo"

    async def complete(self, request):
        from ciel.runtime import ChatChoice, ChatResponse
        prompt = request.messages[-1].content if request.messages else ""
        return ChatResponse(
            choice=ChatChoice(message=ChatMessage(role="assistant", content=f"echo: {prompt}"), finish_reason="stop"),
            metadata={},
        )

    async def stream(self, request):
        return (await self.complete(request),)

    async def models(self):
        from ciel.providers import ModelInfo
        return [ModelInfo(id="echo", provider="echo")]


if __name__ == "__main__":
    import asyncio
    rt = build_runtime()
    result = asyncio.run(rt.run_agent_loop(request=ChatRequest(messages=[ChatMessage(role="user", content="hello")]), tenant_id="default"))
    print(getattr(getattr(result.response, "choice", None), "message", None).content)
'''

_CIEL_YAML = """\
project: {name}
default_tenant: default
providers:
  - name: echo
    base_url: http://localhost:8000/v1
toolsets:
  - name: default
    description: default toolset
"""


def scaffold_project(target: Path, *, force: bool = False) -> List[str]:
    target.mkdir(parents=True, exist_ok=True)
    name = target.resolve().name or "my-ciel-project"
    safe = name.replace("-", "_").replace(" ", "_") or "my_ciel_project"
    module = f"{safe}_agent"

    created: List[str] = []

    def write(rel: str, content: str) -> None:
        p = target / rel
        if p.exists() and not force:
            return
        p.write_text(content, encoding="utf-8")
        created.append(rel)

    write("pyproject.toml", _PYPROJECT.replace("{name}", name).replace("{module}", module))
    write(f"{module}.py", _AGENT.replace("{module}", module))
    write("ciel.yaml", _CIEL_YAML.replace("{name}", name))
    return created
