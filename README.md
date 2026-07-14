# Ciel Agent Framework

Enterprise-grade framework to build model-agnostic, deploy-agnostic autonomous agents and multi-agent systems with harness-first principles.

## Packages

| Package | Purpose |
|---|---|
| `ciel` | Public SDK, CLI entrypoint |
| `ciel.providers` | Model provider interface + adapters |
| `ciel.runtime` | Agent runtime, tooling, memory, skills |
| `ciel.orchestration` | Multi-agent orchestration, durable state, supervisor |
| `ciel.gateway` | Platform adapters, messaging gateway |
| `ciel.security` | Approvals, secret redaction, PII scrubber, sandbox |
| `ciel.observability` | Traces, logs, metrics, audit |
| `ciel.entorno` | Execution backends: local, docker, ssh, processpool |
| `ciel.acp` | ACP server for IDE integrations |

## Installation

```bash
pip install mana-ciel        # PyPI distribution name
# or, with uv:
uv pip install mana-ciel
```

The import name stays `ciel`; the CLI command is `ciel`:

```bash
ciel --help
```

> Note: the PyPI package is named **mana-ciel** (the name `ciel` was already taken
> on PyPI). You still `import ciel` and run `ciel` — only the install name differs.

## Quick start

```bash
pip install mana-ciel
ciel init my-agent          # scaffold a runnable project (offline-safe)
cd my-agent && uv run python my_agent_agent.py
```

Ciel is extensible via plugins: install a third-party package exposing a
`ciel.plugins` entry point and its providers/tools are auto-discovered — no core
edits. See `docs/guide/` for the developer guide.

> **Extensible vía plugins**: instala un paquete que exponga el entry point
> `ciel.plugins` y sus providers/tools se auto-descubren. Ver
> [`docs/guide/plugins.md`](docs/guide/plugins.md).

## Requirements

- Python >= 3.11
- Package manager/distribution: **uv** (recommended) or pip

## Example

End-to-end offline demo: `examples/end_to_end.py`

```bash
uv run examples/end_to_end.py
```

Covers:
- wiring 3 tools through `ciel.runtime.tools`
- running `DefaultAgentRuntime`
- persisting state with `MemoryStore`
- checkpoint/restore with `CheckpointStore`

## Status

### Fase 1 — Runtime básico: ✅ Cerrada
- `ciel.providers` OpenAI-compatible y Anthropic
- runtime agent loop con tool_calls
- tool registry/schema/dispatcher
- memoria SQLite + FTS5
- skills markdown + frontmatter
- checkpoint store
- project context discovery y render
- context compression head/tail/rewrite
- CLI: `ciel run`, `ciel chat -q`, `ciel compression`, `ciel checkpoints` y `ciel info`

### Fase 2 — Gobierno enterprise: ✅ Cerrada
- políticas de approval (manual / smart / yolo) y redacción integradas al runtime
- redacción de secretos + PII scrubber
- auditoría JSONL por session/tenant, traces por tool call
- multi-tenancy en providers/sinks y validación explícita de `tenant_id`
- credential pools, rotación, sandbox de ejecución

### Fase 3 — Multiagente durable: ✅ Cerrada
- orquestación durable por spec YAML (`AgentSpec`/`AgentStep`), supervisor con budget/rate-limit y topologías pipeline/fan-out/debate
- `KanbanBoard` con filtros por status, assignee y tenant; métricas e índices
- `DurableQueue` SQLite WAL
- CLI: `ciel swarm run`, `ciel board add/list/show/assign`

### Fase 4 — Superficies y despliegue: ✅ Cerrada
- `ciel serve` (FastAPI compuesta: control gateway + host MCP `/mcp` + router webhook), offline-safe con echo provider
- `ciel.gateway.mcp` (cliente/servidor), `ciel.acp` (IDE)
- Dockerfile multi-stage (uv), `docker-compose.yml`, Helm chart `deploy/helm/ciel`
- `deploy/example-enterprise`, docs SDK públicas
- release v0.1.0 (wheels + CHANGELOG)

### Fase 5 — Orquestación best-of-breed: ✅ Cerrada (`graph`, `flows`, `chat`, `root`, `session` entregados)
ADK.sub_agents + LangGraph + AutoGen.GroupChat + CrewAI.Flows.

Entregado en esta sesión:
- `ciel.orchestration.graph`: grafo de estado explícito (nodes/edges/estado) con checkpoint + reanudación/time-travel estilo LangGraph, montado sobre el `Supervisor` existente (hereda retry/timeout/budget).
- `ciel.orchestration.flows` (CrewAI.Flows): flows event-driven con `add_start`/`add_listen`/`add_router`/`add_branch`, estado mutable compartido y `resume` de long-running tras interrupción, sobre `Supervisor`.
- `ciel.orchestration.chat` (AutoGen.GroupChat): `GroupChat` + `GroupChatManager` multi-agente conversable, modelo-agnóstico y OFFLINE-SAFE (participantes = funciones locales sobre el transcripto; soporta `max_rounds`, `selector`, `terminate_keyword`, `terminate_if`).
- `ciel.orchestration.root` (ADK.sub_agents): `RootAgent` con ROUTING a `Specialist` agents sobre `Supervisor` (`router(prompt) -> nombre | None`, con `root_handler` de respaldo).
- `ciel.cli.graph`: `ciel graph demo|run|resume` (offline-safe).
- `ciel.cli.flow`: `ciel flow run|resume` (offline-safe, checkpointer opcional).
- `ciel.cli.chat`: `ciel chat group` (demo offline de 3 agentes que converge con TERMINATE).
- Checkpoint stores (`Graph`/`Flow`/`GroupChat`/`Root`) persisten sobre `MemoryStore` (multitenancy nativo).
- `ciel.orchestration.session` (ADK.session_state): `SessionStore` — session state persistente por tenant entre turnos, sobre `MemoryStore` (keys namespaced `session:`), con `append_turn`/`history`, `save_state`/`load_state`, `link_board_task`/`board_links` (integración board+session) y `list_sessions`.
- `ciel.RootRunner.route(prompt, *, session_id, session_store, tenant_id)` mantiene el historial de turnos entre invocaciones (rehidrata `RootState.history`).
- `ciel.cli.root`: `ciel root route <prompt>` (offline-safe, demo con 2 specialists + root handler; opciones `--db`/`--session-id`/`--tenant` para session state persistente).
- Tests de Fase 5: 37 tests verdes (graph 6, flows 6, chat 7, root 7, session 6, root+session 5).

Verificación actual: `uv run pytest tests/` → 153 passed, 1 skipped. `uv run ciel graph demo`, `uv run ciel flow run`, `uv run ciel chat group` y `uv run ciel root route` ejecutan offline.

### Fase 6 — Agencia autónoma en bucle: ✅ Cerrada (`agent` entregado)
AutoGen/ADK: `EventLoop` durable + `AutonomousAgent` sobre `Supervisor` y `SessionStore`.

Entregado en esta sesión:
- `ciel.orchestration.agent` (AutoGen/ADK): agencia autónoma en bucle montada SOBRE `Supervisor` (cada intento de tarea hereda retry/timeout/budget) y SOBRE `SessionStore` (estado por tenant).
  - `Task`: unidad de trabajo durable (`goal`, `payload`, `status`, `attempts`, `result`, `error`) con `snapshot()`/`from_snapshot()` y `mark_running()`/`mark_succeeded()`/`mark_failed()`.
  - `EventLoop`: bucle durable con reintentos exponenciales (backoff `base_delay_s * 2^(n-1)` capped). `run(task, handler, *, run_id)` ejecuta con reintentos y persiste checkpoint tras cada intento; `resume(run_id, handler)` rehidrata desde `MemoryStore` y continúa, completando la tarea tras reinicio (criterio Fase 6). Idempotente si el checkpoint ya está `succeeded`/`failed`.
  - `EventLoopCheckpointStore`: persistencia del estado del loop sobre `MemoryStore` (clave `loop:<run_id>`, multitenancy nativo).
  - `AutonomousAgent`: orquestador de nivel superior; `run_goal(goal, handler, *, plan=None)` descompone el objetivo en tareas y las ejecuta vía `EventLoop`, persistiendo turnos de session por tenant.
- `ciel.cli.loop`: `ciel loop run <goal>` (offline-safe, handler echo local; `--run-id`/`--db`/`--tenant`/`--session-id`) y `ciel loop resume --run-id <id> --db <db>` (reanuda tras reinicio).
- Tests de Fase 6: batería verde en `tests/test_agent_fase6_test.py`.

Verificación actual: `uv run pytest tests/` → 153 + N passed, 1 skipped. `uv run ciel loop run "..." --db /tmp/l.sqlite3 --tenant t1` y `uv run ciel loop resume --run-id <id> --db /tmp/l.sqlite3` ejecutan offline.

### Fase 7 — Enterprise duro: ✅ Cerrada (`enterprise` entregado)
RBAC/OIDC, audit inmutable, cost governance, secrets, rate-limit transversal.

Entregado en esta sesión:
- `ciel.enterprise` (OFFLINE-SAFE, sin dependencias duras): paquete de enterprise duro.
  - `ciel.enterprise.rbac`: `RBACEngine` (roles admin/operator/viewer; permisos con comodín `category:*`; orden tenant>global>denegado) + `OIDCVerifier` (JWT local, `OIDC_AVAILABLE` por detección de PyJWT). Excepciones `RBACError`, `FeatureUnavailable`.
  - `ciel.enterprise.audit`: `HashChainAuditSink(JsonlAuditSink)` — audit INMUTABLE (append-only hash-chained SHA-256); `verify()` detecta alteración; `last_hash()` para encadenar.
  - `ciel.enterprise.cost`: `CostGovernor` (presupuesto por modelo/tenant, alertas y corte) — `estimate`/`record`/`spent`/`budget_of`/`remaining`/`allowed`/`check_budget` (lanza `BudgetExceededError`) / `alerted`. Capa transversal (no acopla al `Supervisor`).
  - `ciel.enterprise.secrets`: `SecretStore` con backends pluggable por prioridad — `EnvSecretBackend`, `KubernetesSecretBackend` (OFFLINE-SAFE), `VaultSecretBackend` (requiere `hvac`; degrada a `FeatureUnavailable` si falta). `get`/`require` (lanza `SecretError`).
  - `ciel.enterprise.ratelimit`: `TenantRateLimiter` — cuotas transversales por tenant/usuario con ventana deslizante en memoria; `check`/`consume` (lanza `RateLimitError`) / `reset` / `remaining`.
- `ciel rbac` / `ciel cost`: CLI offline-safe (Typer + Rich). `ciel rbac check|assign|list-roles`; `ciel cost record|status|check`.
- Tests de Fase 7: 29 tests verdes (rbac 7, audit 5, cost 6, secrets 5, ratelimit 6).

Verificación actual: `uv run pytest tests/` → 194 passed, 1 skipped. `uv run ciel rbac list-roles` y `uv run ciel cost status --tenant t1` ejecutan offline.

### Fase 8 — Deploy HA + observabilidad + madurez: ✅ Cerrada
Helm HA, OTel centralizado, adapters de canal (Teams/Discord/WebUI) y HIL en grafo, runbooks y release v0.2.0 ya entregados y verificados.

Entregado en esta sesión:
- **Helm HA**: chart `deploy/helm/ciel` con `replicaCount: 2`, `PodDisruptionBudget` (minAvailable 1), `HorizontalPodAutoscaler` (2–10 réplicas), `podAntiAffinity` y `topologySpreadConstraints`.
- **OTel centralizado** (`ciel.observability.otel`): `init_tracing(*, otlp_endpoint)` (OTLP o in-memory offline-safe), `current_tracer()`, `span_count()` (corregido para opentelemetry-sdk 1.x). Comando `ciel observe` y flag `--otel`/`--otel-endpoint` en `ciel serve`.
- **Adapters de canal** (`ciel.adapters`): `TeamsAdapter`, `DiscordAdapter`, `WebUIAdapter` + `FakeAdapter` (offline-safe).
- **Routers de gateway** (`ciel.gateway.messaging`): `create_teams_webhook_router`, `create_discord_webhook_router`, `create_webui_router`, montados en `ciel serve`.
- **Human-in-the-loop (HIL)** en `ciel.orchestration.graph`: `GraphNode.require_approval`, `GraphRunner.approve()`/`deny()` con chequeo RBAC (`approve:*`). Pausa y reanuda tras aprobación de rol autorizado.
- **Runbooks** (`docs/runbooks/`): deploy, incidente, rollback, backup de audit/board, escalado HPA.

Verificación actual (smoke): `ciel observe` confirma exporter; grafo con `require_approval` pausa y reanuda tras `approve:*`; tests formales de Fase 8 cerrados (`test_fase8_hil_otel_test.py`, `test_fase8_adapters_test.py`).

### Fase 9 — Plugin system + extensibilidad: ✅ Cerrada
Plugin system, provider Gemini, tools de fábrica, scaffold offline y corrección de bug raíz en la firma de callable de tool.

Entregado en esta sesión:
- **Plugin system** (`ciel.plugins`): `default_registry` con auto-descubrimiento vía entry points `ciel.providers`, `ciel.tools` y `ciel.agents`. Los paquetes de terceros que exponen un entry point `ciel.plugins` se registran sin editar el core.
- **GeminiProvider** añadido a `ciel.providers` builtins (modelo-agnóstico, offline-safe con echo de respaldo).
- **Tools de fábrica** (`ciel.runtime.tools_builtins`): `echo`, `datetime`, `http_get`, `file_read`, `shell` — disponibles out-of-the-box y auto-registradas.
- **`ciel init` scaffold offline**: `ciel init my-agent` genera un proyecto ejecutable sin dependencias de red.
- **Bug raíz corregido**: `ciel.runtime.ToolProvider.execute` usa ahora la firma oficial de callable — `callable_(arguments, *, tool_call_id, tenant_id) -> ToolResult | dict | Any` — alineando tools builtin, de plugin y de usuario.

Verificación actual: `uv run pytest tests/` → 230 passed, 2 skipped (cifra global de la suite tras Fase 9).

## Extending Ciel

Ciel está diseñado para extenderse sin tocar el core:

- **Plugins**: instala cualquier paquete que exponga un entry point `ciel.plugins` (grupos `ciel.providers` / `ciel.tools` / `ciel.agents`) y Ciel lo auto-descubre vía `ciel.plugins.default_registry`. Ver [`docs/guide/plugins.md`](docs/guide/plugins.md).
- **Tools propias**: implementa la firma oficial de tool callable — `callable_(arguments, *, tool_call_id, tenant_id) -> ToolResult | dict | Any` — usada por `ciel.runtime.ToolProvider.execute` (builtins, plugins y tools de usuario comparten la misma firma). Ver [`docs/guide/tools.md`](docs/guide/tools.md).

## License

- Core framework: **AGPL-3.0-or-later**
- Commercial dual license available for regulated deployments.
