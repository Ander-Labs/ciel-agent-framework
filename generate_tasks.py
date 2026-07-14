from __future__ import annotations

from typing import Any


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n"


def render(tasks: dict[str, dict[str, Any]]) -> str:
    blocks: list[str] = [_section("Criterio de avance global", tasks.pop("__meta__", {}).get("objective", ""))]
    for section, data in tasks.items():
        status = data.get("status", "pending")
        checkbox = "- [x]" if status == "completed" else "- [ ]"
        body_lines = [f"{checkbox} {line}" for line in data.get("items", [])]
        body = "\n".join(body_lines)
        if data.get("criterion"):
            body += f"\n\n### Criterion of advance\n{data['criterion']}\n"
        blocks.append(_section(section, body))
    return "\n".join(blocks)


DEFAULT = {
    "§ Criterio de avance global": {
        "objective": "Deploy enterprise en k8s/VPS con tracing, MCP, ACP y un adapter funcional.",
    },
    "Fase 0: Fundación (estado actual: cerrada)": {
        "status": "completed",
        "items": [
            "Repo SDK, CI multi-OS",
            "Contratos base en `ciel.common`, `ciel.providers`, `ciel.runtime`",
            "Multi-tenancy mínimo en providers y seguridad: `ProviderConfig.tenant`, aislamiento por tenant en `OpenAICompatibleProvider`, política de aprobación extendible por tenant",
            "Trazabilidad mínima en `ciel.observability`: `AuditEvent` con tenant metadata, `InMemoryAuditSink` funcional",
            "CLI mínima: `ciel --help`, `ciel doctor`",
        ],
    },
    "Fase 1: Runtime básico (estado actual: cerrada)": {
        "status": "completed",
        "items": [
            "`ciel.providers`: adapter OpenAI canónico sin stubs",
            "`ciel.providers`: adapter Anthropic funcional",
            "`ciel.runtime.agent`: loop de conversation con tool_calls",
            "`ciel.runtime.tools`: tool registry, toolset schema, handlers JSON",
            "`ciel.runtime.memory`: memoria declarativa SQLite + FTS5",
            "`ciel.runtime.skills`: skills markdown frontmatter, carga selectiva",
            "`ciel.runtime.context`: project context files injection",
            "`ciel.runtime.compression`: compresión simple por recorte/rewrite",
            "`ciel.runtime.compression`: gzip/zlib round-trip",
            "`ciel.runtime.checkpoints`: snapshots por sesión",
            "CLI: `ciel run`, `ciel chat -q`",
            "CLI: `/compression`, `/checkpoints`",
            "Verificación ejecutable: `uv pip install -e \".[dev,acp]\"` + `uv run pytest -q` verde",
        ],
    },
    "Fase 2: Gobierno enterprise (estado actual: cerrada)": {
        "status": "completed",
        "items": [
            "`ciel.security.approvals`: manual / smart / yolo",
            "`ciel.security.redaction`: secret redaction + PII scrubber multi-tenant",
            "`ciel.observability.audit`: audit log JSONL por sesión/tenant",
            "`ciel.observability.traces`: trace por tool call con span ID, tenant ID, trace ID",
            "Multi-tenancy: validación explícita de `tenant_id` en runtime y requests",
            "Credential pools por proveedor, rotación, env manager",
            "Sandbox ejecución file/terminal por proceso",
            "Docs: enterprise_fase2.py ejecutable + progreso documentado",
        ],
        "criterion": "Sesión completa reproducible desde archive; modo yolo explícito y auditable.",
    },
    "Fase 3: Multiagente durable (estado actual: siguiente)": {
        "status": "pending",
        "items": [
            "`ciel.orchestration.spec`: AgentSpec en YAML/JSON",
            "`ciel.orchestration.supervisor`: supervisor + workers, failover, timeout, retry",
            "`ciel.orchestration.topology`: fan-out / pipeline / debate",
            "Durable queue, kanban board ligero",
            "Presupuesto y rate-limit por agente/tenant",
            "CLI: `ciel swarm run`, `ciel board list/show/assign`",
        ],
        "criterion": "Pipeline de 3 agentes sobre tarea real, reproducible desde trace, con presupuesto respetado.",
    },
    "Fase 4: Superficies y despliegue (estado actual: bloqueada hasta Fase 3)": {
        "status": "pending",
        "items": [
            "`ciel.gateway.base`: control HTTP API",
            "`ciel.gateway.mcp`: MCP client stdio/HTTP + MCP server host",
            "`ciel.acp`: ACP server compatible IDEs",
            "`ciel.gateway.adapter`: 1 adapter inicial de mensajería",
            "`ciel.deploy`: docker image oficial, Docker Compose",
            "`ciel.deploy`: Helm chart para k8s",
            "Docs: SDK público, ejemplo enterprise, playbooks de despliegue k8s/VPS",
            "Release v0.1.0 público",
        ],
        "criterion": "Deploy enterprise en k8s/VPS con tracing, MCP, ACP y un adapter funcional.",
    },
}
if __name__ == "__main__":
    print(render(DEFAULT))
