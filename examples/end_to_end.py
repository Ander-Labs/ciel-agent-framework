"""End-to-end example for Ciel Agent Framework.

Demonstrates:
- wiring 3 tools via the existing runtime/tools contracts
- sending a prompt through DefaultAgentRuntime
- persisting state with MemoryStore
- checkpointing and restoring via CheckpointStore

Run with:
    uv run examples/end_to_end.py

No external services are required; the example uses a dummy provider so it
works completely offline. The run intentionally exercises tool dispatch,
memory persistence and checkpoint/restore end-to-end.
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping

from ciel.runtime import (
    AgentRuntimeResult,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatChoice,
    DefaultAgentRuntime,
    DefaultToolDispatcher,
    ToolProvider,
    ToolResult,
    ToolSpec,
)
from ciel.runtime.checkpoints import Checkpoint, CheckpointedAgentRuntime, CheckpointStore
from ciel.runtime.memory import MemoryStore
from ciel.runtime.tools import ToolRegistry, ToolsetSchema
from ciel.observability import InMemoryAuditSink
from ciel.providers import ChatProvider


# ---------------------------------------------------------------------------
class DummyProvider(ChatProvider):
    """Offline provider. Returns a fixed assistant message by default."""

    provider_name = "dummy"

    def __init__(self, *, default_response: str = "done") -> None:
        self.default_response = default_response

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=self.default_response, metadata={}),
                finish_reason="stop",
            ),
            metadata={},
        )

    async def stream(self, request: ChatRequest):
        return [await self.complete(request)]

    async def models(self):
        return []


class ToolCallingDummyProvider(ChatProvider):
    """Offline provider that replays tool_calls from the last user message."""

    provider_name = "tool_calling_dummy"

    def __init__(self, *, default_response: str = "done") -> None:
        self.default_response = default_response

    async def complete(self, request: ChatRequest) -> ChatResponse:
        tool_calls: list[dict[str, Any]] = []
        if request.messages:
            last = request.messages[-1]
            if last.role == "user" and isinstance(last.metadata, dict):
                tool_calls = [tc for tc in last.metadata.get("tool_calls", []) if isinstance(tc, dict)]
        finish_reason = "tool_calls" if tool_calls else "stop"
        message = ChatMessage(
            role="assistant",
            content="" if tool_calls else self.default_response,
            tool_calls=tool_calls or None,
            metadata={},
        )
        return ChatResponse(choice=ChatChoice(message=message, finish_reason=finish_reason), metadata={})

    async def stream(self, request: ChatRequest):
        return [await self.complete(request)]

    async def models(self):
        return []
# 2. Three concrete tool callables.
# ---------------------------------------------------------------------------
async def echo_text(*, text: str, **kwargs: Any) -> Dict[str, Any]:
    return {"echo": text}


async def uppercase_text(*, text: str, **kwargs: Any) -> Dict[str, Any]:
    return {"uppercase": text.upper()}


async def reverse_text(*, text: str, **kwargs: Any) -> Dict[str, Any]:
    return {"reversed": text[::-1]}


# ---------------------------------------------------------------------------
# 3. Runtime wiring helper.
# ---------------------------------------------------------------------------
def build_runtime(
    *,
    provider: ChatProvider,
    tool_callables: Mapping[str, Any],
) -> DefaultAgentRuntime:
    specs = [
        ToolSpec(
            name="echo",
            description="Echo input text back to the caller.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        ToolSpec(
            name="uppercase",
            description="Return the uppercase version of the input text.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        ToolSpec(
            name="reverse",
            description="Reverse the input text.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
    ]

    registry = ToolRegistry()
    registry.register_toolset(
        ToolsetSchema(
            name="demo",
            description="Demo toolset with 3 simple tools.",
            tools=specs,
        )
    )

    async def execute(
        *,
        toolset: str,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> ToolResult:
        callable_ = tool_callables.get(name)
        if callable_ is None:
            return ToolResult(id=tool_call_id, name=name, error=f"unknown tool: {name}")
        try:
            output = await callable_(**arguments)
            return ToolResult(id=tool_call_id, name=name, output=output)
        except Exception as exc:  # pragma: no cover
            return ToolResult(id=tool_call_id, name=name, error=str(exc))

    class _InlineToolProvider(ToolProvider):
        async def tool_specs(self, toolset: str) -> Any:
            return tuple(specs)

        async def execute(self, *, toolset: str, name: str, arguments: Dict[str, Any], tool_call_id: str) -> ToolResult:
            return await execute(
                toolset=toolset, name=name, arguments=arguments, tool_call_id=tool_call_id
            )

    dispatcher = DefaultToolDispatcher(provider=_InlineToolProvider(), default_toolset="demo")
    return DefaultAgentRuntime(
        provider=provider,
        dispatcher=dispatcher,
        registry=registry,
        agent="demo-agent",
    )


# ---------------------------------------------------------------------------
# 4. End-to-end scenario.
# ---------------------------------------------------------------------------
async def main() -> int:
    workdir = Path(tempfile.gettempdir()) / "ciel-e2e-demo"
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / "memory.db"
    if db_path.exists():
        db_path.unlink()

    runtime = build_runtime(
        provider=ToolCallingDummyProvider(default_response="ok"),
        tool_callables={
            "echo": echo_text,
            "uppercase": uppercase_text,
            "reverse": reverse_text,
        },
    )
    memory = MemoryStore(str(db_path))
    store = CheckpointStore(memory_store=memory)
    audit_sink = InMemoryAuditSink()
    agent = CheckpointedAgentRuntime(runtime=runtime, store=store, audit_sink=audit_sink)

    session_id = "demo-session"
    tenant_id = "tenant-1"
    tool_call_payload = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "echo", "arguments": {"text": "hello"}},
    }
    prompt = "Use the demo text tools with input='hello'"
    request = ChatRequest(
        messages=(
            ChatMessage(role="system", content="You are a helpful assistant with demo tools.", metadata={}),
            ChatMessage(role="user", content=prompt, metadata={"tool_calls": [tool_call_payload]}),
        ),
        tools=(),
        temperature=0.0,
        extra={"session_id": session_id},
    )

    print("[run] 1) agent loop with checkpoints")
    result = await agent.run_with_checkpoints(
        session_id=session_id,
        request=request,
        checkpoint_after_every=1,
        tenant_id=tenant_id,
        toolset="demo",
    )
    print(f"       response={result.response.choice.message.content!r}")
    print(f"       tool_turns={len(result.loop_results)}")
    for turn in result.loop_results:
        for tool_result in turn.tool_results:
            print(f"         - tool={tool_result.name} output={tool_result.output}")

    print("[memory] record tool execution + app state")
    for turn in result.loop_results:
        for tool_result in turn.tool_results:
            memory.record_tool_execution(
                tenant_id=tenant_id,
                session_id=session_id,
                toolset="demo",
                tool_name=tool_result.name,
                arguments=tool_result.output,
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:01Z",
                duration_ms=1,
                output=tool_result.output,
            )
    memory.set(tenant_id=tenant_id, session_id=session_id, key="last_prompt", value=prompt)
    memory.set(tenant_id=tenant_id, session_id=session_id, key="tool_call_payload", value=tool_call_payload)

    with sqlite3.connect(db_path) as rowconn:
        rowconn.row_factory = sqlite3.Row
        rows = rowconn.execute(
            "SELECT key, value_json FROM memory WHERE tenant_id=? AND session_id=?",
            (tenant_id, session_id),
        ).fetchall()
        print(f"       stored rows={[(row['key'], row['value_json'][:40]) for row in rows]}")

    print("[checkpoint] load auto-saved checkpoint")
    auto_checkpoint_id = result.metadata.get("checkpoint_id") if result.metadata else None
    if not auto_checkpoint_id:
        for lr in result.loop_results:
            if isinstance(lr.metadata, dict):
                cids = lr.metadata.get("checkpoint_ids")
                if cids:
                    auto_checkpoint_id = cids[0]
                    break
    print(f"       auto_checkpoint_id={auto_checkpoint_id}")

    # save an explicit application-level checkpoint we control for the restore phase
    checkpoint_id = auto_checkpoint_id or "manual-1"
    store.save(
        Checkpoint(
            checkpoint_id=checkpoint_id,
            turn_index=len(result.loop_results),
            request=request,
            loop_results=result.loop_results,
            metadata={"session_id": session_id, "agent": "demo-agent"},
        ),
        tenant_id=tenant_id,
        session_id=session_id,
    )
    print(f"       manual saved={checkpoint_id}")

    restored = store.load(tenant_id=tenant_id, session_id=session_id, checkpoint_id=checkpoint_id)
    print(f"       restored={restored is not None} turn_index={restored.turn_index if restored else None}")

    print("[memory] retrieval")
    last_prompt = memory.get(tenant_id=tenant_id, session_id=session_id, key="last_prompt")
    print(f"       last_prompt={last_prompt!r}")
    search_hits = memory.search("hello", limit=5)
    print(f"       search hits={len(search_hits)}")
    for hit in search_hits:
        print(f"         - key={hit['key']} value={hit['value']}")

    print("[restore] resume from checkpoint and run second turn")
    runtime2 = build_runtime(
        provider=ToolCallingDummyProvider(default_response="restored"),
        tool_callables={
            "echo": echo_text,
            "uppercase": uppercase_text,
            "reverse": reverse_text,
        },
    )
    agent2 = CheckpointedAgentRuntime(runtime=runtime2, store=store, audit_sink=audit_sink)
    resume_request = ChatRequest(
        messages=tuple(list(restored.request.messages) + [ChatMessage(role="user", content="Please finish.", metadata={})]),
        tools=(),
        temperature=0.0,
        extra={**restored.request.extra, "session_id": session_id},
    )
    result2 = await agent2.run_with_checkpoints(
        session_id=session_id,
        request=resume_request,
        checkpoint_after_every=1,
        tenant_id=tenant_id,
        toolset="demo",
    )
    print(f"       restored_response={result2.response.choice.message.content!r}")

    memory.close()
    print("[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
