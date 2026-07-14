from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from ciel.observability import AuditEvent, NullAuditSink, propagate
from ciel.runtime import (
    AgentContext,
    AgentRuntimeResult,
    ChatMessage,
    ChatRequest,
    ToolLoopResult,
    ToolResult,
)
from ciel.runtime.memory import MemoryStore


@dataclass
class Checkpoint:
    checkpoint_id: str
    turn_index: int
    request: ChatRequest
    loop_results: Sequence[ToolLoopResult]
    metadata: Dict[str, Any] = field(default_factory=dict)


class CheckpointStore:
    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    def save(self, checkpoint: Checkpoint, *, tenant_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
        payload = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "turn_index": checkpoint.turn_index,
            "request": {
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "name": message.name,
                        "metadata": message.metadata,
                    }
                    for message in checkpoint.request.messages
                ],
                "model": checkpoint.request.model,
                "temperature": checkpoint.request.temperature,
                "max_tokens": checkpoint.request.max_tokens,
                "extra": checkpoint.request.extra,
            },
            "loop_results": [
                {
                    "turn_id": result.turn_id,
                    "finish_reason": result.finish_reason,
                    "tool_results": [
                        {
                            "id": tool_result.id,
                            "name": tool_result.name,
                            "output": tool_result.output,
                            "error": tool_result.error,
                            "usage": tool_result.usage,
                            "duration_ms": tool_result.duration_ms,
                            "metadata": tool_result.metadata,
                        }
                        for tool_result in result.tool_results
                    ],
                    "metadata": result.metadata,
                }
                for result in checkpoint.loop_results
            ],
            "metadata": checkpoint.metadata,
        }
        self.memory.set(
            tenant_id=tenant_id,
            session_id=session_id or checkpoint.request.extra.get("session_id", ""),
            key=f"checkpoint:{checkpoint.checkpoint_id}",
            value=payload,
        )

    def load(self, *, tenant_id: Optional[str], session_id: str, checkpoint_id: str) -> Optional[Checkpoint]:
        payload = self.memory.get(tenant_id=tenant_id, session_id=session_id, key=f"checkpoint:{checkpoint_id}")
        if not isinstance(payload, dict):
            return None
        request = ChatRequest(
            messages=tuple(
                ChatMessage(
                    role=message.get("role", "user"),
                    content=message.get("content", ""),
                    name=message.get("name"),
                    metadata=message.get("metadata", {}),
                )
                for message in payload.get("request", {}).get("messages", [])
            ),
            model=payload.get("request", {}).get("model"),
            temperature=payload.get("request", {}).get("temperature"),
            max_tokens=payload.get("request", {}).get("max_tokens"),
            extra=payload.get("request", {}).get("extra", {}),
        )
        loop_results = []
        for result in payload.get("loop_results", []):
            loop_results.append(
                ToolLoopResult(
                    turn_id=result.get("turn_id", str(uuid.uuid4())),
                    messages=(),
                    tool_results=tuple(
                        ToolResult(
                            id=tool_result.get("id", str(uuid.uuid4())),
                            name=tool_result.get("name", ""),
                            output=tool_result.get("output"),
                            error=tool_result.get("error"),
                            usage=tool_result.get("usage"),
                            duration_ms=tool_result.get("duration_ms"),
                            metadata=tool_result.get("metadata", {}),
                        )
                        for tool_result in result.get("tool_results", [])
                    ),
                    finish_reason=result.get("finish_reason", "stop"),
                    metadata=result.get("metadata", {}),
                )
            )
        return Checkpoint(
            checkpoint_id=payload.get("checkpoint_id", checkpoint_id),
            turn_index=payload.get("turn_index", 0),
            request=request,
            loop_results=tuple(loop_results),
            metadata=payload.get("metadata", {}),
        )


class CheckpointedAgentRuntime:
    def __init__(self, runtime: Any, store: CheckpointStore, *, audit_sink: Optional[Any] = None) -> None:
        self.runtime = runtime
        self.store = store
        self.audit_sink = audit_sink or NullAuditSink()

    async def _emit(self, event: AuditEvent, *, tenant_id: Optional[str] = None) -> AuditEvent:
        normalized = propagate(event, tenant_id=tenant_id)
        await self.audit_sink.write(normalized)
        return normalized

    async def run_with_checkpoints(
        self,
        *,
        session_id: str,
        request: ChatRequest,
        checkpoint_after_every: int = 1,
        tenant_id: Optional[str] = None,
        toolset: Optional[str] = None,
        limit: int = 32,
    ) -> AgentRuntimeResult:
        checkpoint_index = 0
        current_request = request
        while True:
            result = await self.runtime.run_agent_loop(
                request=current_request,
                tenant_id=tenant_id,
                toolset=toolset,
                limit=limit,
            )
            checkpoint_index += len(result.loop_results)
            checkpoint = Checkpoint(
                checkpoint_id=str(uuid.uuid4()),
                turn_index=checkpoint_index,
                request=current_request,
                loop_results=result.loop_results,
                metadata={"session_id": session_id, "agent": getattr(self.runtime, "agent", "default")},
            )
            self.store.save(checkpoint, tenant_id=tenant_id, session_id=session_id)
            await self._emit(
                AuditEvent(
                    event="agent.checkpoint.saved",
                    session_id=session_id,
                    agent=getattr(self.runtime, "agent", "default"),
                    data={"checkpoint_id": checkpoint.checkpoint_id},
                    tenant_id=tenant_id,
                ),
                tenant_id=tenant_id,
            )
            if not result.loop_results or checkpoint_index % max(checkpoint_after_every, 1) != 0:
                break
            latest_turn = result.loop_results[-1]
            appended_messages = list(result.response.choice.messages.tool_calls or [])
            all_messages = list(current_request.messages) + list(result.response.choice.messages)
            current_request = ChatRequest(
                messages=tuple(all_messages),
                tools=current_request.tools,
                model=current_request.model,
                temperature=current_request.temperature,
                max_tokens=current_request.max_tokens,
                extra={**current_request.extra, "session_id": session_id},
            )
        return result
