# Ciel Agent Framework — Project Charter

## 1. Nombre y propósito

Nombre visible: **Ciel Agent Framework**.
Nombre interno/CLI/packages: **ciel**.

Ciel es un **framework SDK + runtime + orquestador** para construir agentes autónomos y multiagentes empresariales.
No es un agente: es el harness y la fábrica que permite crear agentes seguros, trazables, agnósticos en modelo, proveedor e infraestructura.

## 2. Posicionamiento estratégico

Hoy ningún framework ofrece simultáneamente:
- modelo/proveedor agnóstico real sin tradeoffs,
- primitivas enterprise por defecto,
- principios de harness desde el núcleo,
- licencia fuerte AGPL v3 + dual license comercial,
- stack abierto con MCP y A2A.

Ciel existe para cerrar esa brecha.

## 3. Público objetivo

- Equipos de plataforma ML/IA en fintech, banca, seguros, salud, energía y sector público.
- Integradores y consultoras enterprise.
- Startups que requieren soberanía de datos y proveedor sin vendor-lock.

## 4. Antifilosofía

Ciel **no** es:
- un chatbot wrapper sobre una API.
- una plataforma SaaS propietaria.
- un ecosistema cerrado de skills con governance externo.
- una reimplementación monolítica de Hermes Agent sin enterprise features.

## 5. Principios rectores

1. **Harness-first**: runtime, memoria, skills, seguridad y orquestación son core, no addons.
2. **Model-agnostic**: un solo contrato `ModelProvider` soporta cualquier modelo/proveedor.
3. **Deploy-agnostic**: mismo paquete en local, VPS, k8s, modal serverless, on-prem.
4. **Enterprise-by-default**: approvals, redaction, auditoría, multi-tenant, retention por defecto.
5. **Open standard interop**: MCP cliente/servidor y A2A como ciudadanos.
6. **AGPL v3 + dual license comercial**: comunidad con derechos fuertes; clientes regulados con licencia cerrada opcional.
7. **Interface-first**: contratos limpios sobre implementaciones; extensión por composición.
8. **uv-first packaging**: `uv` es la herramienta oficial para dependencias, lockfile, builds y distribución.

## 6. Arquitectura objetivo

| Paquete | Responsabilidad |
|---|---|
| `ciel` | SDK público, CLI entrypoint |
| `ciel.providers` | Model provider interface + adapters |
| `ciel.runtime` | Agent runtime, tooling, memory, skills, compression |
| `ciel.orchestration` | Multi-agent orchestration, durable state, supervisor |
| `ciel.gateway` | Platform adapters, messaging gateway |
| `ciel.security` | Approvals, secret redaction, PII scrubber, sandbox |
| `ciel.observability` | Traces, logs, metrics, audit |
| `ciel.entorno` | Execution backends: local, docker, ssh, modal, processpool |
| `ciel.acp` | ACP server for IDE integrations |

## 7. Stack inicial

- Python >= 3.14
- Pydantic v2, SQLAlchemy 2, HTTPX, Typer, Rich
- SQLite + FTS5 para runtime local
- APScheduler/croniter para scheduling
- FastAPI/Starlette para control API / ACP server
- ProcessPool + políticas de aprobación para sandbox inicial
- Adaptadores base: OpenAI-compatible, Anthropic, Bedrock-compatible placeholder
- Gestión de dependencias, lockfile, builds y distribución: **uv**

## 8. Hoja de ruta

- **Fase 0**: scaffolding, contratos base, CLI mínima.
- **Fase 1**: runtime básico, tools, skills, memoria, compresión y checkpoints.
- **Fase 2**: gobierno enterprise: approvals, redaction, audit y credential pools.
- **Fase 3**: multiagente durable: supervisor, topologías y durable queue.
- **Fase 4**: superficies y despliegue: ACP, MCP, docker/helm, docs SDK.

## 9. Métricas de éxito

- Time-to-agent < 1 hora para un desarrollador con `ciel`.
- Swap time de modelo/proveedor sin modificar lógica del agente.
- Reproducibilidad completa desde trace JSONL.
- Token accounting por sesión, agente y proyecto.
