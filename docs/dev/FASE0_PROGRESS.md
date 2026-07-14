# Fase 0 – Progress

## Observabilidad

- **[completed]** Added `NullAuditSink` — no-op `AuditSink`.
- **[completed]** Added `propagate(event, *, tenant_id=None)` — normalizes `tenant_id`, mutating event only when an override is supplied.
- **[completed]** Added `TraceSpan` dataclass for native multi-tenant tracing with `add_event(...)` and async `start_child(...)`.
- **[completed]** Kept backward compatibility: existing `AuditEvent`, `AuditSink`, `InMemoryAuditSink`, and `assert_tenant_event` behavior unchanged.

## Security

- **[completed]** Added `tenant` to `ApprovalRequest`, `ApprovalDecision`, and `ManualApprovalPolicy` for multi-tenant approval flows.
- **[completed]** Added `TenantIsolationPolicy` with `validate_decision_tenant(...)` static helper.
- **[completed]** Added `PIIScrubber` + `safe_text(...)` for redaction of DNI/email/phone patterns on top of existing secret redaction.

## Runtime

- **[completed]** Added `ChatMessage.tool_calls` for normalized tool-call payloads.
- **[completed]** Added `ToolLoopResult` and `AgentRuntimeResult` dataclasses with `tenant_id` support.
- **[completed]** Added `AgentRuntime` async contract: `run_agent_loop(...)` and `stream_agent_loop(...)`.
- **[completed]** Added `DefaultToolDispatcher.dispatch(...)` `tenant_id` injection and `dispatch_all(...)` batch dispatch with per-call/global tenant fallback.

## Tests

- Ran `uv run pytest`: 24 passed.
- Existing provider/runtime/observability/security tests remain green.
- Multi-tenancy contracts verified end-to-end: provider → runtime dispatch → observability event propagation.
