# Ciel Agent Framework — Roadmap


## Fase 0: Fundación

Entregables:
- [x] repo SDK, CI publica multi-OS
- [x] contratos base en `ciel.common`, `ciel.providers`, `ciel.runtime`
- [x] CLI mínima: `ciel --help`, `ciel doctor`
- [x] pyproject, build wheels, verify install
- [x] `uv.lock`, desarrollo y CI con `uv`
- [x] distribución por `uv build` y `uv publish`

Nota: completado scaffolding y docs. Pendiente: verificar `ciel --help` y `ciel doctor`.

Criterio de avance: `python -m build` genera wheels válidos en Windows/Linux/macOS.

---

## Fase 1: Runtime básico

Entregables:
- [x] `ciel.providers`: adapter OpenAI-compatible
- [x] `ciel.providers`: adapter Anthropic
- [x] `ciel.runtime.agent`: loop de conversation con tool_calls
- [x] `ciel.runtime.tools`: tool registry, toolset schema, handlers JSON
- [x] `ciel.runtime.memory`: memoria declarativa SQLite + FTS5
- [x] `ciel.runtime.skills`: skills markdown frontmatter, carga selectiva
- [x] `ciel.runtime.context`: project context files injection
- [x] `ciel.runtime.compression`: compresión simple por recorte/rewrite
- [x] `ciel.runtime.compression`: gzip/zlib round-trip
- [x] `ciel.runtime.checkpoints`: snapshots por sesión
- [x] CLI: `ciel run`, `ciel chat -q`, `uv run pytest` verde
- [x] CLI: `/compression`, `/checkpoints`

Criterio de avance: crear un agente con 3 tools, hablarle, ejecutar tools, persistir memoria, checkpoint/restore, compresión de contexto y CLI con slash commands.

---

## Fase 2: Gobierno enterprise

Entregables:
- [x] `ciel.security.approvals`: manual / smart / yolo
- [x] `ciel.security.redaction`: secret redaction + PII scrubber
- [x] `ciel.observability.audit`: audit log JSONL por session/tenant
- [x] `ciel.observability.traces`: trace por tool call
- [x] multi-tenancy:
  - [x] `ProviderConfig.tenant` y propagación a `ModelInfo.metadata`
  - [x] Aislamiento por tenant en provider registry y sinks
  - [x] Validación explícita de `tenant_id` en runtime y requests
- [x] credential pools por proveedor, rotación, env manager
- [x] sandbox ejecución file/terminal por proceso
- [x] docs: “Enterprise hardening” y playbooks

Criterio de avance: sesión completa reproducible desde archive; modo yolo explícito y auditable.

---

## Fase 3: Multiagente durable

Entregables:
- [x] `ciel.orchestration.spec`: AgentSpec/AgentStep; to_dict/from_dict/from_yaml/to_dict
- [x] `ciel.orchestration.supervisor`: supervisor con budget/rate-limit
- [x] `ciel.orchestration.topology`: pipeline / fan-out / debate con rechazo por presupuesto
- [x] durable queue SQLite WAL
- [x] kanban board ligero con filtros status/assignee/tenant
- [x] CLI: `ciel swarm run`, `ciel board add/list/show/assign`
- [x] tests CLI ejecutables para swarm/board vía `swarm_app` y `board_app`

Criterio de avance: pipeline reproducible desde `AgentSpec` YAML, presupuesto/rate-limit respetado, suite verde.

---

## Fase 4: Superficies y despliegue

Entregables pendientes:
- [x] `ciel.gateway.base`: control HTTP API (verificado en tests)
- [x] `ciel.gateway.mcp`: MCP client stdio/HTTP + MCP server host (bugs corregidos, verificado)
- [x] `ciel.acp`: ACP server compatible IDEs (estable)
- [x] `ciel.gateway.adapter`: 1 adapter inicial de mensajería (WebhookAdapter integrado)
- [x] `ciel serve`: comando CLI + app compuesta (control + MCP + webhook)
- [x] docker image oficial, Docker Compose, Helm chart
- [x] docs SDK publico, ejemplo enterprise
- [x] release v0.1.0 publico

Nota: Fase 4 completa. Suite verde (82 + 3 smoke tests de `ciel serve`).
Control gateway, MCP host/client, adapter de mensajería, comando `ciel serve`,
Docker/Compose, Helm chart, docs SDK y ejemplo enterprise cerrados y verificados.
Release v0.1.0: wheels generados con `uv build`, `CHANGELOG.md` actualizado.

Criterio de avance: deploy enterprise en k8s/VPS con tracing, MCP, ACP y un adapter funcional.

---

## Fase 5: Orquestación best-of-breed (estado: ✅ CERRADA — graph/flows/chat/root/session entregados)

Mezcla best-of-breed: ADK.sub_agents + LangGraph + AutoGen.GroupChat + CrewAI.Flows.

Entregables:
- [x] **graph** (LangGraph): `ciel.orchestration.graph` — grafo de estado explícito con checkpoint + reanudación/time-travel sobre `Supervisor` (hereda retry/timeout/budget). `ciel graph demo|run|resume` (offline-safe). ✅ ENTREGADO
- [x] **flows** (CrewAI.Flows): `ciel.orchestration.flows` — flows event-driven `add_start`/`add_listen`/`add_router`/`add_branch` con estado y resume de long-running sobre `Supervisor`. `ciel flow run|resume` (offline-safe). ✅ ENTREGADO
- [x] **chat** (AutoGen.GroupChat): `ciel.orchestration.chat` — GroupChat + GroupChatManager multi-agente conversable, modelo-agnóstico y offline-safe. `ciel chat group` (demo de 3 agentes que converge). ✅ ENTREGADO
- [x] **root** (ADK.sub_agents): `ciel.orchestration.root` — root_agent con ROUTING a specialist agents sobre `Supervisor`. ✅ ENTREGADO (core + tests + CLI `ciel root route` offline-safe)
- [x] **session state persistente por tenant entre turnos** (ADK) — `ciel.orchestration.session.SessionStore` sobre `MemoryStore` (multitenancy nativo) + `RootRunner.route(..., session_id, session_store, tenant_id)` rehidrata/persiste turnos + `link_board_task` integra board+session. ✅ ENTREGADO

Criterio de avance (fase completa):
Un flujo crítico modelado como grafo con checkpoint se reanuda tras interrupción;
un group chat de 3 agentes resuelve una tarea en diálogo; root agent enruta a
specialists; session state persistente por tenant entre turnos integrado a board+session;
`ciel graph demo` / `ciel flow run` / `ciel chat group` / `ciel root route` funcionan offline.
Suite verde (153 passed, 1 skipped). ✅ CUMPLIDO — FASE 5 CERRADA.

---

## Fase 6: Agencia autónoma en bucle (AutoGen/ADK)

Entregables:
- [x] Loop de eventos durable con `EventLoop`/`Task` y reintentos exponenciales
- [x] `ciel.orchestration.agent`: agente autónomo con planificación y ejecución (`AutonomousAgent`, `Task`, `EventLoop`)
- [x] Tareas de larga duración con `EventLoop.resume` (reanuda tras reinicio desde checkpoint en `MemoryStore`)
- [x] CLI: `ciel loop run` / `ciel loop resume`
- [x] Tests: event loop reanuda tras reinicio; tarea completa; reintento exponencial ante fallo transitorio

Criterio de avance: una `Task` autónoma se ejecuta y, tras reinicio (resume desde checkpoint en `MemoryStore`), continúa y se completa; los reintentos exponenciales se activan ante fallo transitorio; `ciel loop run`/`ciel loop resume` funcionan offline; suite verde. ✅ CUMPLIDO — FASE 6 CERRADA.

---

## Fase 7: Enterprise duro (RBAC/OIDC, audit inmutable, cost governance)

Entregables:
- [x] RBAC por roles y permisos (`ciel.enterprise.rbac.RBACEngine`) + OIDC para authn (`OIDCVerifier`, JWT local; degrada si falta PyJWT)
- [x] Audit log inmutable (append-only, hash-chain SHA-256) en `ciel.enterprise.audit.HashChainAuditSink` (SOC2-ready, `verify()` lo prueba)
- [x] Cost governance: presupuesto por modelo/tenant, alertas y corte en `ciel.enterprise.cost.CostGovernor` (capa transversal, no acopla al Supervisor)
- [x] Secrets: `ciel.enterprise.secrets.SecretStore` con backends Vault / K8s / env (nunca hardcode; degrada sin `hvac`)
- [x] Rate-limit + cuotas por tenant/usuario en `ciel.enterprise.ratelimit.TenantRateLimiter`
- [x] CLI: `ciel rbac`, `ciel cost`
- [x] Tests: RBAC deniega acceso no autorizado; audit no mutable; cost governance corta por presupuesto

Criterio de avance: RBAC + OIDC + audit inmutable + cost governance operativos; suite verde. ✅ CUMPLIDO — FASE 7 CERRADA.

---

## Fase 8: Deploy HA + observabilidad + madurez de producción

Entregables:
- [x] Helm HA: `replicaCount: 2`, PDB (minAvailable 1), HPA (2–10 réplicas, target CPU 70%), `podAntiAffinity`, `topologySpreadConstraints` (`deploy/helm/ciel`)
- [x] OpenTelemetry centralizado: `init_tracing` (OTLP o in-memory), `span_count`, `ciel observe` + flag `--otel` en `ciel serve`
- [x] Adapters de canal: Teams / Discord / Web UI + FakeAdapter (`ciel.adapters`), routers en `ciel.gateway.messaging` montados en `ciel serve`
- [x] Human-in-the-loop en grafo: `GraphNode.require_approval`, `GraphRunner.approve`/`deny` con chequeo RBAC `approve:*`
- [x] Runbooks: deploy / incidente / rollback / backup audit+board / escalado HPA (`docs/runbooks/`)
- [ ] Tests formales Fase 8 (`test_fase8_hil_otel_test.py`, `test_fase8_adapters_test.py`) — EN CURSO
- [ ] Regresión completa `uv run pytest` verde (194 + N)
- [ ] Release v0.2.0 (tag + wheels + CHANGELOG)

Criterio de avance: deploy HA en k8s con OTel, backups y rollback; suite verde bajo carga.

