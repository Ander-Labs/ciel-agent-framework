# Changelog

All notable changes to this project will be documented in this file.

Dates use release date. Versions follow SemVer with initial pre-release `0.1.0`.

## [0.3.0] — Fase 9 (Extensibilidad: plugins, providers, tools, DX) — 2026-07-14

**Publicado en PyPI**: `pip install mana-ciel==0.3.0` (distribución `mana-ciel`,
import `ciel`). Verificado: install limpio + `default_registry().list_providers()`
expone openai/anthropic/gemini + toolset `builtins`.

### Added
- **Plugin system** (`ciel.plugins`): `PluginRegistry` + `default_registry()` que
  auto-registra builtins y descubre plugins de terceros vía entry points
  (`ciel.providers`, `ciel.tools`, `ciel.agents`). Permite extender el framework
  sin tocar el core (`pip install mi-plugin-ciel`).
- **Providers empaquetados**: `GeminiProvider` (`ciel.providers.gemini`) se suma a
  `OpenAICompatibleProvider` y `AnthropicProvider` (ya existentes). Los tres se
  registran como builtins en `default_registry()`.
- **Tools de fábrica** (`ciel.runtime.tools_builtins`): toolset `builtins` con
  `echo`, `datetime` (offline), `http_get` (inyectable mock client), `file_read`,
  `shell` (sandboxeados vía `ciel.sandbox`).
- **`ciel init`**: scaffold de proyecto (pyproject + agent + ciel.yaml),
  offline-safe e idempotente. El agente generado corre sin red ni API keys.
- **Bug fix** en `ToolRegistry.register_tool`: el `ToolsetSchema.tools` ahora se
  mantiene sincronizado (antes `get_toolset_schema().tools` salía vacío).

### Fixed
- **`ToolProvider.execute` no ejecutaba el callable de la tool** (bug de raíz). El
  provider concreto `ciel.runtime.ToolProvider` (usado por `DefaultToolDispatcher`
  y por tanto por `DefaultAgentRuntime.run_agent_loop`) invocaba el callable con la
  firma equivocada `callable_(context, **arguments)` → `TypeError`/`output=None`.
  Corregido a la firma OFICIAL documentada:
  `callable_(arguments: dict, *, tool_call_id: str, tenant_id: str | None) -> ToolResult | dict | Any`
  (await si es corrutina; excepciones se capturan en `ToolResult.error`; acepta
  `ToolResult` o valor crudo). Alineados `examples/quickstart_agent.py`,
  `tests/gateway_fase4_test.py` y `tests/test_toolcalls_integration_test.py` con
  la firma oficial. Verificado end-to-end vía dispatcher (no solo llamando el
  callable directo).

### Verification
- `uv run pytest tests/` → **230 passed, 2 skipped** (215 base + 13 Fase 9 +
  2 regresión dispatch: `test_fase9_plugins_test.py` 8, `test_fase9_tools_test.py` 7).
- Smoke: `uv run ciel init /tmp/demo` genera proyecto que corre offline
  (`echo: hello`). `default_registry()` expone openai/anthropic/gemini + toolset
  `builtins`. `GeminiProvider` offline (sin api_key lanza; con client mock devuelve
  texto). Docs DX externas en `docs/guide/` (subagente).

## [0.2.0] — Fase 8 (Deploy HA + observabilidad + madurez) — 2026-07-14

### Added
- **Helm HA**: chart `deploy/helm/ciel` con `replicaCount: 2`, `PodDisruptionBudget`
  (`minAvailable: 1`), `HorizontalPodAutoscaler` (2–10 réplicas, target CPU 70%),
  `podAntiAffinity` (topologyKey `kubernetes.io/hostname`) y
  `topologySpreadConstraints` (maxSkew 1). Templates `hpa.yaml` +
  `poddisruptionbudget.yaml`.
- **OTel centralizado** (`ciel.observability.otel`): `init_tracing(*,
  otlp_endpoint)` usa `OTLPSpanExporter` si hay endpoint o `InMemorySpanExporter`
  por defecto (offline-safe); `current_tracer()`, `span_count()` (cuenta spans del
  exporter in-memory), `OtlpAuditExporter` (sink de auditoría como spans). Comando
  `ciel observe` y flag `--otel`/`--otel-endpoint` en `ciel serve`.
- **Adapters de canal** (`ciel.adapters`): `TeamsAdapter`, `DiscordAdapter`,
  `WebUIAdapter` + `FakeAdapter` (offline-safe, fakes en tests). Heredan
  `MessagingAdapter`/`Message` de `ciel.gateway.adapter`.
- **Routers de gateway** (`ciel.gateway.messaging`): `create_teams_webhook_router`,
  `create_discord_webhook_router`, `create_webui_router`, montados en `make_app`
  (`ciel serve`) y exportados en `ciel.gateway.__init__`.
- **Human-in-the-loop (HIL)** en `ciel.orchestration.graph`: `GraphNode.require_approval`,
  `GraphPaused`, `GraphApprovalDenied`, `GraphRunner.approve()`/`deny()` con
  chequeo RBAC (`enterprise.rbac.check(action="approve:*")`). El runner pausa y
  persiste `paused=True`; reanuda tras aprobación de rol autorizado.
- **Runbooks** (`docs/runbooks/`): deploy HA (`deploy.md`), incidente (`incident.md`),
  rollback (`rollback.md`), backup de audit/board (SQLite, `backup.md`), escalado HPA
  (`hpa.md`).

### Fixed
- **Fase 8 — rol `admin` ya incluye `approve:*`**: el HIL (`GraphRunner.approve`)
  exige el permiso `approve:*` (wildcard `category:*`). El `RBACEngine` se corrigió
  para que el rol `admin` por defecto cubra `approve:*`; antes el rol admin no lo
  incluía y el HIL denegaba incluso a administradores. Verificado: `alice` (admin)
  aprueba; `bob` (viewer) es bloqueado por `RBACError`.
- `ciel.observability.otel.span_count()` devolvía `-1` siempre: (1) `init_tracing`
  no persistía `_last_provider` (faltaba `global`); (2) accedía a atributos
  inexistentes en opentelemetry-sdk 1.x (`active_span_processor`/`span_exporter`).
  Ahora navega `provider._active_span_processor._span_processors[].span_exporter`
  vía `_find_in_memory_exporter`.

### Verification
- `uv run pytest tests/` → **216 passed, 1 skipped** (194 base F0–7 + 22 Fase 8:
  `test_fase8_hil_otel_test.py` 8, `test_fase8_adapters_test.py` 14).
- Smoke: `uv run ciel observe` confirma exporter; `init_tracing()` + span →
  `span_count() >= 1`; `ciel serve` monta routers Teams/Discord/WebUI
  (`/v1/messaging/{channel}/health` → 200); grafo con `require_approval` pausa y
  reanuda tras aprobación de rol `admin` (`approve:*`), bob (`viewer`) bloqueado.

### Release
- **Release v0.2.0 etiquetado**: tag git `v0.2.0` creado; wheels generados en
  `dist/`; esta sección de CHANGELOG (`## [0.2.0]`) publicada; doc de upgrade desde
  v0.1.0 documentada.
- **Nota**: la continuación Fase 9 se publicó como **v0.3.0 en PyPI**
  (`pip install mana-ciel==0.3.0`; distribución `mana-ciel`, import `ciel`). Ver
  sección `## [0.3.0]` más arriba.

---

## [Unreleased] — Fase 7 (enterprise duro)

### Added
- `ciel.enterprise` (nuevo paquete): enterprise duro OFFLINE-SAFE, sin
  dependencias duras (OIDC y Vault son backends opcionales que degradan a
  `FeatureUnavailable` si falta su extra).
  - `ciel.enterprise.rbac`: `RBACEngine` (roles admin/operator/viewer por
    defecto; permisos con comodín `category:*`; orden tenant-específico >
    global `*` > denegado; `assign`/`revoke`/`role_of`/`has_permission`/
    `check`/`list_roles`/`snapshot`/`from_snapshot`) + `OIDCVerifier`
    (verifica JWT local con `public_key`, sin red; `OIDC_AVAILABLE` por
    detección de `PyJWT`). Excepciones `RBACError`, `FeatureUnavailable`.
  - `ciel.enterprise.audit`: `HashChainAuditSink(JsonlAuditSink)` — audit
    **inmutable** (append-only hash-chained SHA-256: `hash = sha256(prev_hash ||
    canonical(event))`; `verify(*, tenant_id, session_id) -> bool` detecta
    alteración; `last_hash(...)` para encadenar). Reusa `_jsonl_path` y el lock
    del padre; mantiene `assert_tenant_event`.
  - `ciel.enterprise.cost`: `CostGovernor` (presupuesto por modelo/tenant,
    alertas y corte). `estimate`/`record`/`spent`/`budget_of`/`remaining`/
    `allowed`/`check_budget` (lanza `BudgetExceededError` si se excede) /
    `alerted` (umbral `alert_threshold`). Capa transversal que el gateway/runtime
    consulta (no acopla al `Supervisor`).
  - `ciel.enterprise.secrets`: `SecretStore` con backends pluggable por
    prioridad — `EnvSecretBackend` (os.getenv), `KubernetesSecretBackend`
    (archivos montados por K8s, OFFLINE-SAFE), `VaultSecretBackend` (requiere
    `hvac`; si falta `VAULT_AVAILABLE=False` y `get` lanza `FeatureUnavailable`).
    `get`/`require` (lanza `SecretError` si ausente). Nunca hardcodea secretos.
  - `ciel.enterprise.ratelimit`: `TenantRateLimiter` — cuotas transversales por
    tenant/usuario con ventana deslizante en memoria. `check`/`consume` (lanza
    `RateLimitError`) / `reset` / `remaining`. Clave efectiva: `(tenant,user)` >
    `(tenant,"*")` > `("*","*")`.
- `ciel rbac` / `ciel cost`: CLI offline-safe (Typer + Rich). `ciel rbac
  check|assign|list-roles`; `ciel cost record|status|check`.
- Tests Fase 7 (29 verdes): `test_rbac_fase7_test.py` (7), `test_audit_fase7_test.py`
  (5), `test_cost_fase7_test.py` (6), `test_secrets_fase7_test.py` (5),
  `test_ratelimit_fase7_test.py` (6).
- **Fase 7 CERRADA**: RBAC deniega sin rol; audit inmutable verificable; costo
  corta al superar presupuesto; secretos por backend sin hardcode; cuotas
  transversales; `ciel rbac`/`ciel cost` offline; core+CLI+tests verdes.

### Changed
- `ciel.enterprise.__init__` re-exporta todos los símbolos de la fase.
- `ciel.cli.main` registra los grupos `rbac` y `cost` (lazy import).

### Notes
- `hvac` NO está instalado en el entorno: `VaultSecretBackend` degrada a
  `VAULT_AVAILABLE=False` y `get` lanza `FeatureUnavailable` (cumple OFFLINE-SAFE).
  El `pyproject.toml` aún no declara un extra para `hvac`; el módulo funciona sin él.

## [Unreleased] — Fase 6 (agencia autónoma en bucle)

### Added
- `ciel.orchestration.agent` (estilo AutoGen/ADK): agencia autónoma en bucle
  montada SOBRE `Supervisor` (cada intento de tarea hereda retry/timeout/budget
  por worker) y SOBRE `SessionStore` (estado por tenant).
  - `Task`: unidad de trabajo durable (`goal`, `payload`, `status`,
    `attempts`, `result`, `error`) con `snapshot()`/`from_snapshot()` y
    `mark_running()`/`mark_succeeded()`/`mark_failed()`.
  - `EventLoop`: bucle durable con reintentos exponenciales (backoff
    `base_delay_s * 2^(n-1)` capped a `max_delay_s`). `run(task, handler, *,
    run_id)` ejecuta con reintentos y persiste checkpoint tras cada intento;
    `resume(run_id, handler)` rehidrata desde `MemoryStore` y continúa,
    completando la tarea tras reinicio (criterio de avance Fase 6). Idempotente
    si el checkpoint ya está `succeeded`/`failed`. Lanza `TaskError` si el
    handler falla siempre; `EventLoopError` si `resume` no tiene checkpoint.
  - `EventLoopCheckpointStore`: persistencia del estado del loop sobre
    `MemoryStore` (clave `loop:<run_id>`, namespaced; multitenancy nativo:
    `tenant_id=None` → `"__none__"`).
  - `AutonomousAgent`: orquestador de nivel superior. `run_goal(goal, handler, *,
    plan=None)` descompone el objetivo en tareas (una por paso de `plan`, o una
    sola si `plan=None`) y las ejecuta vía `EventLoop`; tras cada tarea completa
    persiste un turno en `SessionStore` (ADK session_state entre ejecuciones).
  - Excepciones: `AgentError`, `EventLoopError`, `TaskError`.
- `ciel loop run <goal>` y `ciel loop resume --run-id <id> --db <db>`: CLI
  offline-safe (Typer + Rich) para el loop autónomo; handler echo local, sin
  red ni proveedor. Opciones `--run-id`/`--db`/`--tenant`/`--session-id`.
- Tests Fase 6 en `tests/test_agent_fase6_test.py`: batería verde (snapshot
  round-trip, run completa en 1 intento, reintento exponencial transitorio,
  fallo permanente → `TaskError`/`failed`, checkpoint save/load, resume tras
  reinicio, resume idempotente, resume sin checkpoint → `EventLoopError`,
  `run_goal` 1 tarea, `run_goal` con plan de 3, integración `SessionStore`,
  multitenancy en checkpointer).
- **Fase 6 CERRADA**: `EventLoop` ejecuta una `Task` y tras reinicio (`resume`
  desde checkpoint en `MemoryStore`) continúa y la completa; los reintentos
  exponenciales se activan ante fallo transitorio; `ciel loop run`/`ciel loop
  resume` funcionan offline; cada pieza (agent / eventloop) tiene core + CLI +
  tests verdes y está documentada; suite verde.

### Changed
- `ciel.orchestration.__init__` exporta ahora `Task`, `EventLoop`,
  `EventLoopCheckpointStore`, `EventLoopStep`, `AutonomousAgent`, `AgentError`,
  `EventLoopError`, `TaskError`.
- `ciel.cli.main` registra el grupo `loop` (lazy import).

### Fixed
- Ninguno en código existente. El core nuevo documenta dos trampas del patrón:
  (1) el `Supervisor` ya hace sus propios reintentos, así que para que
  `EventLoop` controle los reintentos de forma limpia se usa
  `Supervisor(max_attempts=1)` + `EventLoop(max_attempts=N)` en tests/CLI;
  (2) el checkpoint se namespacia por `session_id or run_id`, por lo que
  `resume` debe usar el mismo `--session-id` (o ninguno a ambos).

## [Unreleased] — Fase 5 (orquestación best-of-breed)

### Added
- `ciel.orchestration.flows` (estilo CrewAI.Flows): Flows event-driven con
  `add_start`/`add_listen`/`add_router`/`add_branch`, estado mutable compartido,
  y `resume` de long-running tras interrupción. Montado SOBRE `Supervisor`
  (hereda retry/timeout/budget). `FlowCheckpointStore` persiste sobre `MemoryStore`
  (multitenancy nativo).
- `ciel.orchestration.chat` (estilo AutoGen.GroupChat): `GroupChat` +
  `GroupChatManager` multi-agente conversable, modelo-agnóstico y OFFLINE-SAFE
  (los participantes son funciones locales sobre `GroupChatState.transcript`).
  Soporta `max_rounds`, `selector` round-robin, `terminate_keyword` y
  `terminate_if`. `GroupChatCheckpointStore` persiste el transcripto.
- `ciel.orchestration.root` (estilo ADK.sub_agents): `RootAgent` con ROUTING a
  `Specialist` agents vía `router(prompt) -> nombre | None`; si devuelve None
  usa `root_handler`. Montado SOBRE `Supervisor`. `RootCheckpointStore` persiste
  la decisión de enrutamiento.
- `ciel flow run|resume` y `ciel chat group`: CLI offline-safe (Typer + Rich) para
  los módulos flows y chat.
- 20 nuevos tests de Fase 5 (flows 6, chat 7, root 7) → suite total **142 passed, 1 skipped**.
- `ciel.orchestration.session` (estilo ADK.session_state): `SessionStore` — session state
  persistente por tenant entre turnos, sobre `MemoryStore` (multitenancy nativo: `tenant_id=None`
  ya se normaliza a `"__none__"`). API: `append_turn`, `history`, `save_state`/`load_state`,
  `link_board_task`/`board_links`, `list_sessions`. Keys namespaced con `session:`.
- `ciel.RootRunner.route` ahora acepta `session_id`/`session_store`/`tenant_id` y mantiene
  session state entre turnos: rehidrata `RootState.history` con turnos previos y persiste el
  turno resultante (`_persist_turn`). `RootState` ganó el campo `history` con snapshot/restore.
- `ciel root route <prompt>`: CLI offline-safe del root agent (demo con 2 specialists + root
  handler; opciones `--db`/`--session-id`/`--tenant` para session state persistente).
- 11 nuevos tests de cierre de Fase 5 (session 6, root+session 5) → suite total **153 passed, 1 skipped**.
- **Fase 5 CERRADA**: grafo con checkpoint reanuda, group chat converge, root enruta a specialists,
  session state por tenant entre turnos integrado a board+session, y `graph`/`flow`/`chat`/`root`
  funcionan offline.

### Changed
- `ciel.orchestration.__init__` exporta ahora `Flow`/`FlowRunner`/`FlowState`/
  `FlowError`/`FlowCheckpointStore`, `Agent`/`ChatMessage`/`GroupChat`/
  `GroupChatManager`/`GroupChatState`/`GroupChatError`/`GroupChatCheckpointStore`,
  `RootAgent`/`RootRunner`/`RootState`/`Specialist`/`RootAgentError`/
  `RootCheckpointStore`, `SessionStore`/`SessionError`.
- `ciel.cli.main` registra los grupos `flow`, `chat` y `root` (lazy import).

### Fixed
- `FlowRunner._ready` ya no activa ramas (`add_branch`) sin fuente como si fueran
  `start`: una rama sólo se ejecuta cuando un router la activa explícitamente.
- `add_router` valida destinos contra pasos ya registrados en `compile()`; se
  añadió `add_branch` para registrar ramas de forma explícita (elimina el
  orden frágil de registro).

## 0.1.2 — Fase 5 (cierre: session state por tenant) — 2026-07-11

### Added
- `ciel.orchestration.session.SessionStore`: session state durable por `(tenant_id, session_id)`
  sobre `MemoryStore` (multitenancy nativo), con `append_turn`/`history`, `save_state`/`load_state`,
  `link_board_task`/`board_links` (integración board+session) y `list_sessions`.
- `RootRunner.route(prompt, *, session_id, session_store, tenant_id)`: mantiene el historial de
  turnos entre invocaciones (estilo ADK) y lo rehidrata en `RootState.history`.
- `ciel root route`: CLI del root agent (offline-safe, con session state persistente opcional).
- `tests/test_session_fase5_test.py` (6) + `tests/test_root_session_fase5_test.py` (5).

### Verification
- `uv run pytest tests/` → 153 passed, 1 skipped (base 142 + 11 de cierre de Fase 5).
- `uv run ciel root route "SELECT * FROM users" --db /tmp/s.db --session-id s1 --tenant t1` persiste
  el turno; una 2ª invocación con el mismo `--session-id`/`--db` recupera `history` previo.

## 0.1.0 — 2026-07-08

### Added
- Runtime base: `AgentRuntime`, `DefaultAgentRuntime`, tool-loop con tool_calls, streaming y auditoría sincronizada por sesión/tenant.
- Proveedores: `ChatProvider` abstracto + `OpenAICompatibleProvider`, `AnthropicProvider` y `ProviderRegistry`/`ProviderFactory`.
- Herramientas: `Tool`, `ToolSpec`, `ToolRegistry`, `StaticToolProvider`, `ToolsetSchema`, multi-tenancy por toolset.
- Gobierno: `ApprovalPolicy`, `SmartApprovalPolicy`, `YoloApprovalPolicy`, `ManualApprovalPolicy`, `PIIRedactionPolicy`, multi-tenancy por request.
- Observabilidad: `AuditEvent`, `InMemoryAuditSink`, `NullAuditSink`, emisión de eventos start/end/tool/dispatch.
- Orquestación durable: `AgentSpec`/`AgentStep`, YAML/TOML/dict roundtrip, `Supervisor` con budget/rate-limit.
- Topologías: `TopologyEngine` para `pipeline`, `fan-out` y `debate`, con rechazo temprano por presupuesto excedido.
- Cola durable: `DurableQueue` con SQLite WAL.
- Kanban: `KanbanBoard`, `BoardTask`, filtros por status/assignee/tenant y métricas.
- CLI: `ciel run`, `ciel chat -q`, `ciel compression`, `ciel checkpoints`, `ciel info`, `ciel swarm run`, `ciel board add/list/show/assign`.
- Credenciales: scaffolding multi-tenant con `credentials`.
- Gateway MCP: scaffolding cliente/servidor/transports/integración dentro de `ciel.gateway.mcp`.
- ACP: scaffolding en `ciel.acp` para integraciones IDE.
- Empaquetado: layout `src/`, extras `dev/docs/acp/gateway/security`, CI baseline con pytest verde.

### Changed
- Repo estabilizado para Python >= 3.14 y `uv`.
- Agregada documentación inicial orientada a release en `README.md`, `docs/dev/INDEX.md`, `docs/sdk/README.md` y `CHANGELOG.md`.

### Security
- `redaction` y `approvals` integrados al runtime y providers.
- Multi-tenancy propagado por runtime, observabilidad y providers.

## 0.1.0 — Fase 4 (Superficies y despliegue) — 2026-07-08

### Added (Fase 4)
- `ciel.gateway.server.make_app()`: app FastAPI compuesta que monta control gateway + host MCP (`/mcp`) + router webhook (`/v1/messaging/webhook`) en un solo puerto, con runtime offline (echo provider) por defecto y provider remoto configurable vía `CIEL_PROVIDER_URL`.
- Comando CLI `ciel serve` (Typer) que arranca la app compuesta con uvicorn (`--host`, `--port`, `--tenant`), leyendo `CIEL_TENANT` por defecto.
- `tests/serve_smoke_test.py`: smoke test de `/health` en las tres superficies + validación de que `/v1/agent/run` sigue exigiendo `tenant_id` (400).
- Dockerfile multi-stage (uv) que instala extras `[gateway,acp]` y corre `ciel serve` como entrypoint, con volumen de audit `/var/lib/ciel/audit`.
- `docker-compose.yml`: control gateway + volumen de audit persistente.
- Helm chart en `deploy/helm/ciel`: Deployment con probes `/health` (liveness/readiness), Service, ConfigMap de tenant por defecto y PVC de audit.
- `docs/sdk/README.md`: guía pública del SDK con APIs reales (`make_app`, `create_control_app`, `mount_mcp_app`, `create_webhook_router`, `ciel serve`).
- `deploy/example-enterprise`: ejemplo enterprise con `ciel.yaml` (config central), `config.py` (loader yaml+env) y `serve.py` (arranque con uvicorn).

### Changed (Fase 4)
- `ciel.gateway`: exporta `make_app`.
- Docs del SDK corregidas para apuntar a símbolos reales (antes referenciaban `ciel.gateway.mcp.server.create_app` y `cielo.acp:app` inexistentes).

### Security (Fase 4)
- Multi-tenancy estricto preservado en la app compuesta: `/v1/agent/run` y `/v1/tools/...` devuelven 400 si no hay `tenant_id` (ni default configurado).
- El Docker/Helm no fijan API keys en plaintext: se resuelven desde variables de entorno / Secret.

## 0.1.1 — Fase 5 (Orquestación best-of-breed, arranque) — 2026-07-10

### Added (Fase 5, módulo graph)
- `ciel.orchestration.graph`: grafo de estado explícito estilo LangGraph, montado SOBRE el `Supervisor` existente (cada nodo hereda retry/timeout/budget/rate-limit por worker).
  - `StateGraph`: `add_node`, `add_edge`, `add_conditional_edges`, `set_entry_point`, `set_finish_point`, `compile`.
  - `GraphState`: estado mutable compartido (`data`, `visited`, `current_node`, `last_output`) con `snapshot()` / `from_snapshot()`.
  - `GraphRunner`: `run`, `resume` (reanudación tras interrupción), `run_from` (time-travel hasta `up_to_node`).
  - `GraphCheckpointStore`: persistencia de checkpoint sobre `MemoryStore` con clave `(tenant_id, session_id, key)` — multitenancy nativo.
- `ciel.cli.graph`: subcomando `ciel graph demo|run|resume` (offline-safe, sin proveedor).
- `tests/test_graph_fase5_test.py`: 6 tests verdes (lineal, condicional, reanudación tras interrupción, time-travel, validación de entry point, fallo propagado).

### Fixed (bugs de raíz que afectaban a todo el framework offline)
- `ciel.runtime.memory.MemoryStore`: con `tenant_id=None` se insertaban filas duplicadas (SQLite no trata dos `NULL` como iguales para `UNIQUE`), dejando checkpoints/board leyendo estado obsoleto. Corregido normalizando `tenant_id=None` a un sentinel `"__none__"` en `set`/`get`/`delete`/`record_tool_execution`.
- `MemoryStore.get`/`delete` con `tenant_id=None` ahora hacen round-trip correcto (antes `WHERE tenant_id = NULL` nunca coincidía).
- `GraphRunner.resume` retoma desde el nodo *siguiente* al último completado (antes re-ejecutaba el último nodo, duplicándolo).
- `GraphRunner._run_node` acepta funciones de nodo síncronas o async.

### Verificación
- `uv run pytest tests/` → 122 passed, 1 skipped (subió de 116 a 122).
- `uv run ciel graph demo` ejecuta el grafo offline y muestra el resumen.

### Pendiente en Fase 5
- `ciel.orchestration.flows`: Flows event-driven estilo CrewAI.
- `ciel.orchestration.chat`: GroupChat conversable estilo AutoGen.
- `ciel.orchestration.root`: root_agent routing a specialists estilo ADK.
- Session state por tenant entre turnos integrado a board+session.
- `ciel flow run`, `ciel chat --group`.
