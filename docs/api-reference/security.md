# `ciel.security` — Seguridad y aprobaciones

Políticas de aprobación de ejecución de herramientas y redacción de secretos /
PII para aislamiento multi-tenant.

Incluye el contrato `ApprovalPolicy` y sus variantes
(`ManualApprovalPolicy`, `TenantIsolationPolicy`, `SmartApprovalPolicy`,
`YoloApprovalPolicy`), los DTOs `ApprovalRequest` / `ApprovalDecision`, el
constructor `from_name`, y las utilidades de redacción (`PIIScrubber`,
`redact_string`, `redact_secrets`).

::: ciel.security
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.security.approvals
    options:
      show_root_heading: false
      members: true

::: ciel.security.redaction
    options:
      show_root_heading: false
      members: true

## Sandbox de ejecución (v0.9)

Guardrails y sandbox de ejecución de código del agente. Incluye
`SandboxExecutor` con backends seleccionables (`INPROCESS`, `LIGHT`, `DOCKER`,
`GVISOR`; degradación graceful a `INPROCESS` cuando el backend fuerte no está
disponible), `SandboxLimits` / `ExecResult`, `GuardrailMiddleware` (rate-limit
por tenant + redacción de salida + truncado) y `SandboxContext` (política
`SandboxPolicy` sobre capacidades terminal/file, respaldada por ejecución real).

::: ciel.sandbox
    options:
      show_root_heading: false
      members: true
