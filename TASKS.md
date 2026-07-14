# Ciel Agent Framework — TASKS (roadmap ejecutable)

Criterio de avance global: framework enterprise, model-agnostic y deploy-agnostic,
con multitenancy nativo, skills evolutivos y orquestación best-of-breed, desplegable
en k8s/VPS con tracing, MCP, ACP y adapters funcionales.

Estado base verificado (2026-07-10): **116 passed, 1 skipped**, release v0.1.0
(wheels + CHANGELOG), Dockerfile / Compose / Helm operativos. Fases 0–4 CERRADAS.

---

- [x] ## Fase 0: Fundación (estado: cerrada)
- [x] Repo SDK, CI multi-OS
- [x] Contratos base en `ciel.common`, `ciel.providers`, `ciel.runtime`
- [x] Multi-tenancy mínimo en providers y seguridad: `ProviderConfig.tenant`, aislamiento por tenant en `OpenAICompatibleProvider`, política de aprobación extendible por tenant
- [x] Trazabilidad mínima en `ciel.observability`: `AuditEvent` con tenant metadata, `InMemoryAuditSink` funcional
- [x] CLI mínima: `ciel --help`, `ciel doctor`

### Criterion of advance
`python -m build` genera wheels válidos en Windows/Linux/macOS; CLI base operativa.

---

- [x] ## Fase 1: Runtime básico (estado: cerrada)
- [x] `ciel.providers`: adapter OpenAI canónico sin stubs
- [x] `ciel.providers`: adapter Anthropic funcional
- [x] `ciel.runtime.agent`: loop de conversation con tool_calls
- [x] `ciel.runtime.tools`: tool registry, toolset schema, handlers JSON
- [x] `ciel.runtime.memory`: memoria declarativa SQLite + FTS5
- [x] `ciel.runtime.skills`: skills markdown frontmatter, carga selectiva
- [x] `ciel.runtime.context`: project context files injection
- [x] `ciel.runtime.compression`: compresión simple por recorte/rewrite
- [x] `ciel.runtime.compression`: gzip/zlib round-trip
- [x] `ciel.runtime.checkpoints`: snapshots por sesión
- [x] CLI: `ciel run`, `ciel chat -q`
- [x] CLI: `/compression`, `/checkpoints`
- [x] Verificación ejecutable: `uv pip install -e ".[dev,acp]"` + `uv run pytest -q` verde

### Criterion of audio
Agente con 3 tools, conversación con tool_calls, memoria persistida, checkpoint/restore,
compresión de contexto y CLI con slash commands, todo verde en pytest.

---

- [x] ## Fase 2: Gobierno enterprise (estado: cerrada)
- [x] `ciel.security.approvals`: manual / smart / yolo
- [x] `ciel.security.redaction`: secret redaction + PII scrubber multi-tenant
- [x] `ciel.observability.audit`: audit log JSONL por sesión/tenant
- [x] `ciel.observability.traces`: trace por tool call con span ID, tenant ID, trace ID
- [x] Multi-tenancy: validación explícita de `tenant_id` en runtime y requests
- [x] Credential pools por proveedor, rotación, env manager
- [x] Sandbox ejecución file/terminal por proceso
- [x] Docs: enterprise_fase2 + progreso documentado

### Criterion of advance
Sesión completa reproducible desde archive; modo yolo explícito y auditable.

---

- [x] ## Fase 3: Multiagente durable (estado: cerrada)
- [x] `ciel.orchestration.spec`: AgentSpec en YAML/JSON
- [x] `ciel.orchestration.supervisor`: supervisor + workers, failover, timeout, retry
- [x] `ciel.orchestration.topology`: fan-out / pipeline / debate
- [x] Durable queue (SQLite WAL) + kanban board ligero (persistencia SQLite vía `--db`/`CIEL_BOARD_DB`)
- [x] Presupuesto y rate-limit por agente/tenant
- [x] CLI: `ciel swarm run`, `ciel board add/list/show/assign`
- [x] Tests CLI ejecutables para swarm/board vía `swarm_app` y `board_app`

### Criterion of advance
Pipeline de 3 agentes sobre `AgentSpec` YAML real, reproducible desde trace, con
presupuesto respetado y board persistente entre invocaciones.

---

- [x] ## Fase 4: Superficies y despliegue (estado: cerrada)
- [x] `ciel.gateway.base`: control HTTP API (`/health`, `/v1/agent/run`, `/v1/tools/...`, `/v1/board/list`)
- [x] `ciel.gateway.mcp`: MCP client stdio/HTTP + MCP server host (bugs corregidos)
- [x] `ciel.acp`: ACP server compatible IDEs (estable)
- [x] `ciel.gateway.adapter`: WebhookAdapter + SlackAdapter integrados
- [x] `ciel.gateway.server.make_app()`: app compuesta (control + MCP `/mcp` + webhook) + `ciel serve`
- [x] `ciel.gateway.base`: streaming SSE `POST /v1/agent/run/stream`
- [x] `ciel.deploy`: Dockerfile multi-stage (uv), Docker Compose, Helm chart (probes/Service/PVC)
- [x] Docs SDK público (`docs/sdk/README.md`), ejemplo enterprise (`deploy/example-enterprise`)
- [x] Release v0.1.0 público (wheels + CHANGELOG)

### Criterion of advance
Deploy enterprise en k8s/VPS con tracing, MCP, ACP y un adapter funcional; suite verde
(116 passed / 1 skipped).

---

# ════════════════════════════════════════════════════════════════════════════
# FASE 5+ — MADUREZ BEST-OF-BREED (lo que sigue)
# ════════════════════════════════════════════════════════════════════════════
#
# Tesis (ver docs/dev/FASE5_DESIGN.md): ciel NO copia un solo framework. Hereda
# de Hermes Agent (tools, skills como memoria procedimental, memory cross-session,
# delegación de subagentes, MCP nativo) y compone lo mejor de ADK, LangGraph,
# AutoGen, CrewAI y LlamaIndex como MÓDULOS sobre ese núcleo.
#
# Diferenciador de mercado defendible: agentes evolutivos (skills que aprenden)
# + multitenancy nativo + orquestación best-of-breed.
#
# Orden de ejecución (MVP → producción):
#   Fase 5  → Orquestación best-of-breed (grafo de estado, flows, group chat)
#   Fase 6  → Runtime evolutivo (skills que aprenden, RAG, code exec)
#   Fase 7  → Enterprise duro (RBAC/OIDC, audit inmutable, cost governance)
#   Fase 8  → Deploy HA + observabilidad + madurez de producción

- [x] ## Fase 5: Orquestación best-of-breed (estado: CERRADA — módulos graph/flows/chat/root + session entregados y verificados)
# ADK.sub_agents + LangGraph + AutoGen.GroupChat + CrewAI.Flows
- [x] `ciel.orchestration.graph`: grafo de estado explícito (nodes/edges/estado) con checkpoint + reanudación/time-travel (patrón LangGraph) — SOBRE Supervisor existente (hereda retry/timeout/budget)
- [x] `ciel.orchestration.GraphCheckpointStore`: persistencia de checkpoint sobre `MemoryStore` (multitenancy nativo)
- [x] `ciel.cli.graph`: subcomando `ciel graph demo|run|resume` (offline-safe)
- [x] Tests: 6 tests verdes (lineal, condicional, reanudación tras interrupción, time-travel, validación entry, fallo propagado)
- [x] `ciel.orchestration.flows`: Flows event-driven (`add_start`/`add_listen`/`add_router`/`add_branch`, state, resume de long-running) estilo CrewAI — SOBRE Supervisor
- [x] `ciel.orchestration.FlowCheckpointStore`: persistencia sobre `MemoryStore` (multitenancy nativo)
- [x] `ciel.cli.flow`: subcomando `ciel flow run|resume` (offline-safe, checkpointer opcional)
- [x] Tests flows: 6 tests verdes (lineal, router una rama, reanudación, validación compile/runtime, max_steps)
- [x] `ciel.orchestration.chat`: GroupChat + GroupChatManager multi-agente conversable (revisión de código/planes) estilo AutoGen — modelo-agnóstico y offline-safe
- [x] `ciel.orchestration.GroupChatCheckpointStore`: persistencia del transcripto sobre `MemoryStore`
- [x] `ciel.cli.chat`: subcomando `ciel chat group` (demo offline de 3 agentes que converge con TERMINATE)
- [x] Tests chat: 7 tests verdes (group chat de 3 agentes converge, orden/roles, max_rounds, selector, terminate_if, checkpoint, sin participantes)
- [x] `ciel.orchestration.root`: root_agent que hace ROUTING a specialist agents (ADK.sub_agents) sobre el supervisor existente
- [x] `ciel.orchestration.RootCheckpointStore`: persistencia de la decisión de enrutamiento sobre `MemoryStore`
- [x] Tests root: 7 tests verdes (enruta a specialist, router None -> root, errores, duplicado, compile, checkpoint)
- [x] `ciel.orchestration.session`: SessionStore — session state persistente por tenant entre turnos (ADK) sobre `MemoryStore` (multitenancy nativo), integrado a board+session
- [x] `ciel.RootRunner.route` mantiene session state entre turnos (recupera/append turnos vía SessionStore)
- [x] `ciel root route` (CLI del root agent) — offline-safe, con `--db`/`--session-id`/`--tenant` para session state persistente
- [x] Tests session: 6 tests verdes; Tests root+session: 5 tests verdes
- [x] Tests: grafo con checkpoint reanuda tras interrupción (✅ ya cubierto por graph/flows); group chat converge (✅ ya cubierto)

### Criterion of advance
Un flujo crítico modelado como grafo con checkpoint se reanuda tras interrupción;
un group chat de 3 agentes resuelve una tarea en diálogo; root agent enruta a
specialists. Suite verde.

---

- [x] ## Fase 6: Agencia autónoma en bucle (estado: CERRADA — módulo agent entregado y verificado)
# AutoGen/ADK: EventLoop durable + AutonomousAgent sobre Supervisor y SessionStore
- [x] `ciel.orchestration.agent`: `Task` durable (snapshot/from_snapshot, mark_running/succeeded/failed)
- [x] `ciel.orchestration.EventLoop`: bucle durable con reintentos exponenciales (backoff capped), `run(task, handler, *, run_id)` y `resume(run_id, handler)` — reanuda tras reinicio desde checkpoint en `MemoryStore`
- [x] `ciel.orchestration.EventLoopCheckpointStore`: persistencia del estado del loop sobre `MemoryStore` (multitenancy nativo, clave `loop:<run_id>`)
- [x] `ciel.orchestration.AutonomousAgent`: orquestador que descompone un objetivo en tareas (`run_goal(goal, handler, *, plan=None)`) y las ejecuta vía `EventLoop`, persistiendo turnos de session por tenant (`SessionStore`)
- [x] `ciel loop run <goal>`: CLI offline-safe (handler echo local) con `--run-id`/`--db`/`--tenant`/`--session-id`
- [x] `ciel loop resume --run-id <id> --db <db>`: reanuda un loop interrumpido tras reinicio
- [x] Tests Fase 6: batería verde en `tests/test_agent_fase6_test.py` (snapshot round-trip, run 1 intento, reintento exponencial transitorio, fallo permanente → TaskError/failed, checkpoint save/load, resume tras reinicio, resume idempotente, resume sin checkpoint → EventLoopError, run_goal 1 tarea, run_goal plan de 3, integración SessionStore, multitenancy en checkpointer)
- [x] **Fase 6 CERRADA**: `EventLoop` ejecuta una `Task` y tras reinicio (`resume`) continúa y la completa; reintentos exponenciales ante fallo transitorio; `ciel loop run`/`ciel loop resume` offline; cada pieza con core + CLI + tests verdes y documentada; suite verde

### Criterion of advance
Una `Task` autónoma se ejecuta y, tras reinicio (resume desde checkpoint en `MemoryStore`), continúa y se completa; los reintentos exponenciales se activan ante fallo transitorio; `ciel loop run`/`ciel loop resume` funcionan offline. Suite verde.

---

- [x] ## Fase 7: Enterprise duro (estado: CERRADA — paquete `enterprise` entregado y verificado)
# capa transversal: auth, audit, cost governance
- [x] `ciel.enterprise.rbac`: `RBACEngine` (roles admin/operator/viewer, permisos con comodín `category:*`, orden tenant>global>denegado) + `OIDCVerifier` (JWT local, `OIDC_AVAILABLE` por detección de PyJWT). Excepciones `RBACError`, `FeatureUnavailable`.
- [x] `ciel.enterprise.audit`: `HashChainAuditSink(JsonlAuditSink)` — audit INMUTABLE (append-only hash-chained SHA-256); `verify()` detecta alteración; `last_hash()` para encadenar.
- [x] `ciel.enterprise.cost`: `CostGovernor` (presupuesto por modelo/tenant, alertas y corte) — `estimate`/`record`/`spent`/`budget_of`/`remaining`/`allowed`/`check_budget` (lanza `BudgetExceededError`) / `alerted`. Capa transversal (no acopla al `Supervisor`).
- [x] `ciel.enterprise.secrets`: `SecretStore` con backends pluggable por prioridad — `EnvSecretBackend`, `KubernetesSecretBackend` (OFFLINE-SAFE), `VaultSecretBackend` (requiere `hvac`; degrada a `FeatureUnavailable` si falta). `get`/`require` (lanza `SecretError`).
- [x] `ciel.enterprise.ratelimit`: `TenantRateLimiter` — cuotas transversales por tenant/usuario con ventana deslizante en memoria; `check`/`consume` (lanza `RateLimitError`) / `reset` / `remaining`.
- [x] `ciel.enterprise.__init__`: re-exporta todos los símbolos.
- [x] `ciel rbac` / `ciel cost`: CLI offline-safe (Typer + Rich). `ciel rbac check|assign|list-roles`; `ciel cost record|status|check`.
- [x] Tests Fase 7: 29 tests verdes (rbac 7, audit 5, cost 6, secrets 5, ratelimit 6).
- [x] **Fase 7 CERRADA**: RBAC deniega sin rol; audit inmutable verificable; costo corta al superar presupuesto; secretos por backend sin hardcode; cuotas transversales; `ciel rbac`/`ciel cost` offline; core+CLI+tests verdes y documentados; suite verde.

### Criterion of advance
Usuario sin rol correcto es rechazado; trail de auditoría es inmutable y verificable; costo por tenant se detiene al superar presupuesto; secretos resueltos por backend sin hardcode; cuotas transversales por tenant/usuario. Suite verde.

---

- [x] ## Fase 8: Deploy HA + madurez producción (estado: EN PROGRESO — Helm HA, OTel centralizado, adapters Teams/Discord/WebUI y HIL en grafo entregados; tests formales + runbooks + release v0.2.0 en curso)
# Helm/observabilidad/deploy
- [x] `deploy/helm/ciel`: HA — `replicaCount: 2`, `PodDisruptionBudget` (minAvailable: 1), `HorizontalPodAutoscaler` (2–10 réplicas, target CPU 70%), `podAntiAffinity` (topologyKey kubernetes.io/hostname), `topologySpreadConstraints` (maxSkew 1). Templates `hpa.yaml` + `poddisruptionbudget.yaml`.
- [x] `ciel.observability.otel`: OTel centralizado — `init_tracing(*, otlp_endpoint)` (OTLP exporter si endpoint, si no `InMemorySpanExporter` offline-safe), `current_tracer()`, `span_count()` (cuenta spans del exporter in-memory; **corregido** para opentelemetry-sdk 1.x: `provider._active_span_processor._span_processors[].span_exporter`). `ciel observe` (CLI) + flag `--otel`/`--otel-endpoint` en `ciel serve`.
- [x] `ciel.adapters`: nueva capa de messaging — `TeamsAdapter`, `DiscordAdapter`, `WebUIAdapter` + `FakeAdapter` (offline-safe, fakes en tests). Heredan `MessagingAdapter`/`Message` de `ciel.gateway.adapter`.
- [x] `ciel.gateway.messaging`: routers `create_teams_webhook_router` / `create_discord_webhook_router` / `create_webui_router` montados en `make_app` (`ciel serve`) y exportados en `ciel.gateway.__init__`.
- [x] `ciel.orchestration.graph` (HIL): `GraphNode.require_approval`, `GraphPaused`, `GraphApprovalDenied`, `GraphRunner.approve()`/`deny()` con chequeo RBAC (`enterprise.rbac.check(action="approve:*")`). Pausa y persiste `paused=True`; reanuda tras aprobación de rol autorizado.
- [x] `docs/runbooks/`: runbook_deploy, runbook_incident, runbook_rollback, runbook_backup (audit/board SQLite), runbook_scaling (HPA).
- [x] Tests formales Fase 8: `tests/test_fase8_hil_otel_test.py` (HIL + OTel, 8 tests) y `tests/test_fase8_adapters_test.py` (adapters + gateway routers, 14 tests) — ✅ verdes.
- [x] Regresión completa `uv run pytest tests/` verde: **216 passed, 1 skipped** (194 base F0–7 + 22 Fase 8).
- [ ] Release v0.2.0: tag + wheels + CHANGELOG (sección `## [0.2.0]`) + doc de upgrade desde v0.1.0.

### Criterion of advance
Chart despliega N≥2 réplicas con PDB + HPA y sobrevive a la caída de 1; OTel envía traces/metrics (o in-memory en tests) sin romper offline; `ciel chat`/`ciel flow` reciben/emiten por Teams/Discord/Web UI (fakes en tests); nodo de grafo `require_approval` pausa y reanuda tras aprobación de rol autorizado (`approve:*`); runbooks documentados; release v0.2.0 etiquetado; suite verde (194 + N tests Fase 8).

---

- [x] ## Fase 9: Extensibilidad — plugin system, providers reales, tools de fábrica, DX (estado: EN PROGRESO — core + tests verdes; docs DX externas en curso vía subagente)
- [x] `ciel.plugins`: `PluginRegistry` + `default_registry()` — auto-registra builtins y descubre plugins de terceros por entry points (`ciel.providers`, `ciel.tools`, `ciel.agents`). Extensión sin tocar el core.
- [x] `ciel.providers.gemini`: `GeminiProvider` (Google AI Studio/Vertex) se suma a `OpenAICompatibleProvider` y `AnthropicProvider` (builtins registrados).
- [x] `ciel.runtime.tools_builtins`: toolset `builtins` (`echo`, `datetime`, `http_get`, `file_read`, `shell`) sandboxeado.
- [x] `ciel init`: scaffold de proyecto (pyproject + agent + ciel.yaml), offline-safe e idempotente; el agente generado corre sin red.
- [x] Bug fix: `ToolRegistry.register_tool` sincroniza `ToolsetSchema.tools` (antes `get_toolset_schema().tools` salía vacío).
- [x] Tests formales Fase 9: `tests/test_fase9_plugins_test.py` (8) + `tests/test_fase9_tools_test.py` (5) — ✅ verdes.
- [ ] Docs DX externas `docs/guide/` (quickstart ejecutable, conceptos, providers, tools, plugins, deploy) + `mkdocs.yml` + `examples/quickstart_agent.py` — EN CURSO (subagente).
- [ ] Regresión completa + commit + push (tag v0.3.0).

### Criterion of advance
Tercero puede `pip install mi-plugin-ciel` y su provider/tool aparece en el registry sin import manual; `ciel init` genera proyecto que corre offline; docs externas con quickstart ejecutable; suite verde.
