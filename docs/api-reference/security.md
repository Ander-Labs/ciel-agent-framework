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
