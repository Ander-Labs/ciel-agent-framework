# Prompt de continuación — Ciel Agent Framework

Este archivo es el contexto de arranque para la siguiente sesión. Sustituye
cualquier instrucción previa del proyecto. Léelo completo al iniciar y sigue el
LOOP de la sección 5.

Fecha de corte: 2026-07-13. Estado verificado en esa fecha: **194 passed, 1 skipped**.

---

## 1. Identidad y objetivo

Ciel Agent Framework: framework enterprise para construir agentes autónomos y
sistemas multi-agente, model-agnostic y deploy-agnostic, con multitenancy y
trazabilidad nativas (k8s/VPS). Principio: harness-first, ejecutable sobre
planificación extendida.

Mezcla best-of-breed (de `docs/Prompt.md` original / análisis): ADK.sub_agents
+ LangGraph + AutoGen.GroupChat + CrewAI.Flows + LlamaIndex.

---

## 2. Estado verificado (al cierre de la sesión 2026-07-12)

- **Fases 0–5: CERRADAS.** Runtime, providers (OpenAI/Anthropic), gobierno
  (approvals/redaction/audit), observabilidad, orquestación durable
  (spec/supervisor/topology/queue/board), gateway (MCP/ACP/adapter), CLI,
  Docker/Compose/Helm, release v0.1.0 (wheels + CHANGELOG). Orquestación
  best-of-breed completa: módulos `graph`, `flows`, `chat`, `root` y `session`
  ENTREGADOS Y VERIFICADOS. Todos montados SOBRE `Supervisor` (heredan
  retry/timeout/budget) y con checkpoint stores sobre `MemoryStore`
  (multitenancy nativo).
- **Fase 5: CERRADA — session state entregado.** El último pendiente de Fase 5
  (session state persistente por tenant entre turnos, estilo ADK, integrado a
  board+session) se entregó y verificó en esta sesión.

  ### 2.1 Módulo `graph` (LangGraph) — ENTREGADO
  - `src/ciel/orchestration/graph.py`: grafo de estado explícito estilo LangGraph.
    API: `StateGraph`, `GraphNode`, `GraphState`, `GraphEdge`, `GraphRunner`,
    `GraphCheckpointStore`. Métodos: `run`, `resume` (reanudación tras
    interrupción), `run_from` (time-travel hasta `up_to_node`).
  - `src/ciel/cli/graph.py` + registro en `src/ciel/cli/main.py`
    (`app.add_typer(_load_graph_group(), name="graph")`): `ciel graph demo|run|resume`.
  - `tests/test_graph_fase5_test.py`: 6 tests verdes.

  ### 2.2 Módulo `flows` (CrewAI.Flows) — ENTREGADO
  - `src/ciel/orchestration/flows.py`: Flows event-driven estilo CrewAI sobre
    `Supervisor`. API: `Flow`, `FlowRunner`, `FlowState`, `FlowError`,
    `FlowCheckpointStore`. Métodos de `Flow`: `add_start`, `add_listen`,
    `add_router`, `add_branch`, `compile`. Métodos de `FlowRunner`: `run`,
    `resume`. `FlowState` tiene `data`, `results`, `completed`, `last_event`,
    `snapshot()`/`from_snapshot()`.
  - `src/ciel/cli/flow.py` + registro en `main.py`
    (`app.add_typer(_load_flow_group(), name="flow")`): `ciel flow run|resume`
    (offline-safe, checkpointer opcional `--db`/`--run-id`/`--tenant`).
  - `tests/test_flows_fase5_test.py`: 6 tests verdes.

  ### 2.3 Módulo `chat` (AutoGen.GroupChat) — ENTREGADO
  - `src/ciel/orchestration/chat.py`: GroupChat + GroupChatManager conversable
    estilo AutoGen, modelo-agnóstico y OFFLINE-SAFE (participantes = funciones
    locales sobre `GroupChatState.transcript`; sin red ni proveedor). API:
    `Agent`, `ChatMessage`, `GroupChat`, `GroupChatManager`, `GroupChatState`,
    `GroupChatError`, `GroupChatCheckpointStore`. `GroupChat` soporta
    `max_rounds`, `selector` (round-robin por defecto), `terminate_keyword`
    (por defecto `TERMINATE`); `Agent` soporta `terminate_if(text)->bool`.
    `GroupChatState` tiene `transcript`, `rounds`, `terminated`, `terminator`,
    `snapshot()`/`from_snapshot()`.
  - `src/ciel/cli/chat.py` + registro en `main.py`
    (`app.add_typer(_load_chat_group(), name="chat"`): `ciel chat group`
    (demo offline de 3 agentes que converge con TERMINATE; opciones
    `--message`/`--rounds`/`--tenant`).
  - `tests/test_chat_fase5_test.py`: 7 tests verdes.

  ### 2.4 Módulo `root` (ADK.sub_agents) — ENTREGADO
  - `src/ciel/orchestration/root.py`: root_agent con ROUTING a specialist agents
    estilo ADK sobre `Supervisor`. API: `RootAgent`, `RootRunner`, `RootState`,
    `Specialist`, `RootAgentError`, `RootCheckpointStore`. `RootAgent`:
    `add_specialist`, `set_router(prompt->nombre|None)`, `set_root_handler`,
    `compile`. `RootRunner.route(prompt)` ejecuta el specialist elegido o el
    `root_handler` si el router devuelve None. `RootState` tiene `prompt`,
    `route`, `result`, `handled_by_root`, `metadata`, `history` (turnos previos
    de session), `snapshot()`/`from_snapshot()`.
  - `src/ciel/cli/root.py` + registro en `main.py`
    (`app.add_typer(_load_root_group(), name="root"`): `ciel root route <prompt>`
    (offline-safe, demo con 2 specialists + root handler; opciones
    `--db`/`--session-id`/`--tenant` para session state persistente).
  - `tests/test_root_fase5_test.py`: 7 tests verdes.

  ### 2.5 Módulo `session` (ADK.session_state) — ENTREGADO (cierre de Fase 5)
  - `src/ciel/orchestration/session.py`: `SessionStore` — session state
    persistente por tenant entre turnos sobre `MemoryStore` (multitenancy
    nativo: `tenant_id=None` ya se normaliza a `"__none__"` en `MemoryStore`).
    API: `append_turn`, `history`, `save_state`, `load_state`, `link_board_task`,
    `board_links`, `list_sessions`. Keys namespaced con `session:`.
  - Integración en `RootRunner.route(*, session_id, session_store, tenant_id)`:
    rehidrata `RootState.history` con turnos previos y persiste el turno
    resultante (`_persist_turn`). Cumple el criterio ADK "session state
    persistente entre turnos" SIN red ni proveedor.
  - Integración board+session: `SessionStore.link_board_task`/`board_links`
    vincula tareas del `KanbanBoard` (mismo `tenant_id`) con la session.
  - `tests/test_session_fase5_test.py`: 6 tests verdes.
  - `tests/test_root_session_fase5_test.py`: 5 tests verdes (history entre
    turnos, acumulación por root_handler, supervivencia a nuevo runner,
    list_sessions, aislamiento por tenant).

  - `src/ciel/orchestration/__init__.py` exporta todos los símbolos anteriores
    (`graph`, `flows`, `chat`, `root`, `session`).
  - `docs/dev/FASE5_PROGRESS.md`: progreso de la fase (CERRADA).
- **Suite completa: 153 passed, 1 skipped.** `uv run ciel graph demo`,
  `uv run ciel flow run`, `uv run ciel chat group` y `uv run ciel root route`
  ejecutan offline.

- **Fase 6: CERRADA — agencia autónoma en bucle entregada.** El módulo
  `ciel.orchestration.agent` (AutoGen/ADK: `EventLoop` durable + `AutonomousAgent`)
  se entregó y verificó. Montado SOBRE `Supervisor` (cada intento de tarea hereda
  retry/timeout/budget) y SOBRE `SessionStore` (estado por tenant).
  - `Task`: unidad de trabajo durable (`goal`, `payload`, `status`, `attempts`,
    `result`, `error`) con `snapshot()`/`from_snapshot()` y
    `mark_running()`/`mark_succeeded()`/`mark_failed()`.
  - `EventLoop`: bucle durable con reintentos exponenciales (backoff
    `base_delay_s * 2^(n-1)` capped). `run(task, handler, *, run_id)` ejecuta con
    reintentos y persiste checkpoint tras cada intento; `resume(run_id, handler)`
    rehidrata desde `MemoryStore` y continúa, completando la tarea tras reinicio.
    Idempotente si el checkpoint ya está `succeeded`/`failed`.
  - `EventLoopCheckpointStore`: persistencia del estado del loop sobre `MemoryStore`
    (clave `loop:<run_id>`, multitenancy nativo).
  - `AutonomousAgent`: orquestador de nivel superior; `run_goal(goal, handler, *,
    plan=None)` descompone el objetivo en tareas y las ejecuta vía `EventLoop`,
    persistiendo turnos de session por tenant.
  - `tests/test_agent_fase6_test.py`: 12 tests verdes.
  - `ciel.cli.loop`: `ciel loop run <goal>` (offline-safe, handler echo local;
    `--run-id`/`--db`/`--tenant`/`--session-id`) y `ciel loop resume --run-id <id>
    --db <db>` (reanuda tras reinicio).
- **Fase 7: CERRADA — enterprise duro entregado.** Nuevo paquete `ciel.enterprise`
  (OFFLINE-SAFE, sin dependencias duras: OIDC y Vault degradan a `FeatureUnavailable`
  si falta su extra). Todos los módulos verificados con tests verdes.
  - `ciel.enterprise.rbac`: `RBACEngine` (roles admin/operator/viewer por defecto;
    permisos con comodín `category:*`; orden tenant-específico > global `*` >
    denegado; `assign`/`revoke`/`role_of`/`has_permission`/`check`/`list_roles`/
    `snapshot`/`from_snapshot`) + `OIDCVerifier` (JWT local con `public_key`, sin
    red; `OIDC_AVAILABLE` por detección de PyJWT). Excepciones `RBACError`,
    `FeatureUnavailable`.
  - `ciel.enterprise.audit`: `HashChainAuditSink(JsonlAuditSink)` — audit INMUTABLE
    (append-only hash-chained SHA-256: `hash = sha256(prev_hash || canonical(event))`;
    el primer evento usa `prev_hash=""`); `verify(*, tenant_id, session_id) -> bool`
    detecta alteración; `last_hash(...)` para encadenar. Reusa `_jsonl_path` y el lock
    del padre; mantiene `assert_tenant_event`.
  - `ciel.enterprise.cost`: `CostGovernor` (presupuesto por modelo/tenant, alertas y
    corte) — `estimate`/`record`/`spent`/`budget_of`/`remaining`/`allowed`/
    `check_budget` (lanza `BudgetExceededError` si excede) / `alerted`. Capa
    transversal que el gateway/runtime consulta (no acopla al `Supervisor`).
  - `ciel.enterprise.secrets`: `SecretStore` con backends pluggable por prioridad —
    `EnvSecretBackend` (os.getenv), `KubernetesSecretBackend` (archivos montados por
    K8s, OFFLINE-SAFE), `VaultSecretBackend` (requiere `hvac`; si falta
    `VAULT_AVAILABLE=False` y `get` lanza `FeatureUnavailable`). `get`/`require`
    (lanza `SecretError` si ausente). Nunca hardcodea secretos.
  - `ciel.enterprise.ratelimit`: `TenantRateLimiter` — cuotas transversales por
    tenant/usuario con ventana deslizante en memoria. `check`/`consume` (lanza
    `RateLimitError`) / `reset` / `remaining`. Clave efectiva: `(tenant,user)` >
    `(tenant,"*")` > `("*","*")`.
  - `ciel.enterprise.__init__`: re-exporta todos los símbolos.
  - `ciel rbac` / `ciel cost`: CLI offline-safe (Typer + Rich). `ciel rbac
    check|assign|list-roles`; `ciel cost record|status|check`.
  - Tests Fase 7 (29 verdes): `test_rbac_fase7_test.py` (7),
    `test_audit_fase7_test.py` (5), `test_cost_fase7_test.py` (6),
    `test_secrets_fase7_test.py` (5), `test_ratelimit_fase7_test.py` (6).
- **Suite completa (cierre Fase 7): 194 passed, 1 skipped.** `uv run ciel loop run`,
  `uv run ciel loop resume`, `uv run ciel rbac list-roles` y `uv run ciel cost status
  --tenant t1` ejecutan offline.

### Bugs de raíz YA corregidos (no reintroducir)
1. `ciel.runtime.memory.MemoryStore`: con `tenant_id=None` insertaba filas
   duplicadas (SQLite no trata dos NULL como iguales para UNIQUE). Corregido
   normalizando `tenant_id=None` a sentinel `__none__` en `set`/`get`/`delete`/
   `record_tool_execution`. Esto afectaba checkpoints/board offline en TODO el framework.
2. `GraphRunner.resume` retoma desde el nodo *siguiente* al último completado
   (antes re-ejecutaba el último nodo, duplicándolo).
3. `GraphRunner._run_node` acepta funciones de nodo síncronas o async.
4. `FlowRunner._ready` ya no activa ramas (`add_branch`) sin fuente como si fueran
   `start`: una rama sólo se ejecuta cuando un router la activa explícitamente.
5. `add_router` valida destinos contra pasos ya registrados en `compile()`; se
   añadió `add_branch` para registrar ramas de forma explícita (elimina el orden
   frágil de registro en tiempo de definición).
6. `RootState` debe incluir SIEMPRE el campo `history` en `snapshot()`/
   `from_snapshot()` (agregado en el cierre de Fase 5); no quitarlo ni romper
   el round-trip de session state.

---

## 3. Backlog (qué falta)

### Fase 5 — Orquestación best-of-breed (CERRADA)
- [x] `ciel.orchestration.graph` (LangGraph): grafo de estado + checkpoint + reanudación/time-travel.
- [x] `ciel.orchestration.flows` (CrewAI): `add_start`/`add_listen`/`add_router`/`add_branch` + `resume`.
- [x] `ciel.orchestration.chat` (AutoGen): GroupChat + GroupChatManager offline-safe.
- [x] `ciel.orchestration.root` (ADK): root_agent routing a specialists.
- [x] `ciel.orchestration.session` (ADK session state): persistente por tenant entre turnos, integrado a board+session.
- [x] CLI: `ciel graph demo|run|resume`, `ciel flow run|resume`, `ciel chat group`, `ciel root route`.
- [x] Tests Fase 5: 37 verdes (graph 6, flows 6, chat 7, root 7, session 6, root+session 5).
- [x] **Fase 5 CERRADA** (criterio de avance cumplido; ver sección 6).

### Fase 6 — Agencia autónoma en bucle (AutoGen/ADK) — CERRADA
- [x] `ciel.orchestration.agent`: agente autónomo con planificación y ejecución (montado sobre `Supervisor` y `SessionStore` existentes).
- [x] `EventLoop`/`Task` durable con reintentos exponenciales; estado persistido (checkpoint) sobre `MemoryStore`; `EventLoop.resume` tras reinicio.
- [x] `AutonomousAgent.run_goal` descompone el objetivo en tareas y las ejecuta vía `EventLoop`, persistiendo turnos de session.
- [x] CLI: `ciel loop run`/`ciel loop resume` (offline-safe, `--db`/`--run-id`/`--tenant`/`--session-id`).
- [x] Tests de Fase 6: 12 verdes (`test_agent_fase6_test.py`).
- [x] **Fase 6 CERRADA** (criterio de avance cumplido; ver sección 7).

### Fase 7 — Enterprise duro (RBAC/OIDC, audit inmutable, cost governance) — CERRADA
- [x] `ciel.enterprise.rbac`: `RBACEngine` + `OIDCVerifier` (JWT local; degrada si falta PyJWT).
- [x] `ciel.enterprise.audit`: `HashChainAuditSink(JsonlAuditSink)` — audit inmutable (append-only hash-chained SHA-256), `verify()` detecta alteración.
- [x] `ciel.enterprise.cost`: `CostGovernor` (presupuesto por modelo/tenant, alertas y corte; capa transversal).
- [x] `ciel.enterprise.secrets`: `SecretStore` con backends Vault / K8s / env (nunca hardcode; degrada sin `hvac`).
- [x] `ciel.enterprise.ratelimit`: `TenantRateLimiter` — cuotas transversales por tenant/usuario (ventana deslizante).
- [x] CLI: `ciel rbac`, `ciel cost` (offline-safe).
- [x] Tests Fase 7: 29 verdes (rbac 7, audit 5, cost 6, secrets 5, ratelimit 6).
- [x] **Fase 7 CERRADA** (criterio de avance cumplido; ver sección 7).

### Fase 8 — Deploy HA + observabilidad + madurez (SIGUIENTE)
Reutiliza lo YA existente en el repo (no reimplementar): `deploy/helm/ciel`
(Deployment+Service+PVC audit con probes; FASE 4), `observability/otel.py`
(trazas) y `observability/metrics.py` (Prometheus), `observability/audit.py` +
`enterprise/audit.HashChainAuditSink`, `gateway` (MCP/ACP/adapter) y
`enterprise.*` (auth/cost/ratelimit) como middleware transversal.
- [ ] **Helm HA**: añadir a `deploy/helm/ciel` — `PodDisruptionBudget` (minAvailable),
      `HorizontalPodAutoscaler` (sobre métrica de requests/CPU), `affinity`
      anti-affinity `podAntiAffinity` (esparcir réplicas), `topologySpreadConstraints`,
      y un template `chart`/values para réplicas >1 por defecto. Rollback automático
      documentado en runbooks.
- [ ] **OTel centralizado**: exportador OTel (traces/metrics/logs) que envíe a un
      collector; reutilizar `observability/otel.py` y `metrics.py` (prometheus).
      `ciel observe` o flag `--otel` en `ciel serve`. Tests: spans se emiten.
- [ ] **Adapters** Teams / Discord / Web UI: nueva capa `ciel.adapters` (hoy solo
      Webhook + Slack en gateway). `ciel chat`/`ciel flow` deben poder recibir y
      emitir por estos canales offline-safe (fakes en tests).
- [ ] **Human-in-the-loop (HIL)**: interrupt en `ciel.orchestration.graph`
      (`GraphNode` con `require_approval`/`on_approve`) que pause el `GraphRunner`
      y reanude vía `resume` tras aprobación; integra con `enterprise.rbac.check`
      (solo roles con permiso `approve:*` pueden aprobar). Tests: nodo pausa y
      reanuda tras aprobación.
- [ ] **Runbooks**: `docs/runbooks/` — despliegue, incidente, rollback, backup de
      audit/board (SQLite), escalado HPA.
- [ ] **Release v0.2.0**: tag + wheels + CHANGELOG; docs de upgrade desde v0.1.0.
- [ ] Tests de carga/smoke HA (opcional): `ciel serve` con N réplicas vía
      `uv run`/compose, verificar health + checkpoint compartido.
- [ ] Documentar en `docs/dev/FASE8_PROGRESS.md` + diseño en `docs/dev/FASE8_DESIGN.md`.

---

## 4. Convenciones OBLIGATORIAS del proyecto

- **Entorno:** Windows, Python >= 3.14, gestor `uv`. Terminal = git-bash/MSYS
  (usar rutas estilo Unix dentro de `terminal`; rutas con letra de unidad
  `A:\Apps\...` para archivos entregables).
- **Layout:** `src/` (paquete `ciel`), tests en `tests/`.
- **Estilo de código:** dataclasses + métodos `async` donde aplique; SIN stubs ni
  `...` sin implementar; types explícitos; respetar el estilo de los archivos vecinos
  (ver `supervisor.py`, `topology.py`, `board.py`, `swarm.py`, `root.py`, `session.py`).
- **Multitenancy nativo:** todo estado persiste con `(tenant_id, session_id, key)`
  vía `MemoryStore` (ya normaliza `tenant_id=None` a `"__none__"`).
- **Offline-safe:** los demos/CLI no deben requerir red ni proveedor real (usar
  echo provider o funciones locales sobre `state_data`).
- **Reutilización:** montar sobre `Supervisor`/`TopologyEngine`/`Queue`/`SessionStore`
  existentes, no reimplementar. El grafo/flows/root/session ya heredan
  retry/timeout/budget del Supervisor.
- **Documentación (mantener siempre al día):**
  - `TASKS.md` (raíz): roadmap por fases con checkboxes; marca lo cerrado y lo siguiente.
  - `docs/ROADMAP.md`: fases 0–8 con entregables y criterio de avance.
  - `docs/dev/INDEX.md`: índice de progreso + comandos de verificación.
  - `docs/dev/FASE{N}_PROGRESS.md`: qué se entregó, bugs corregidos, pendiente.
  - `docs/dev/FASE{N}_DESIGN.md`: diseño best-of-breed del módulo (si aplica).
  - `CHANGELOG.md`: entrada por release/fase (Added/Fixed/Verification/Pending).
  - `README.md`: sección Status coherente con lo cerrado.

---

## 5. LOOP de trabajo (seguir para cada módulo/nueva pieza)

1. **Leer primero.** Antes de escribir, lee el código relevante existente
   (`src/ciel/orchestration/*.py`, `src/ciel/runtime/*.py`, CLI vecina) para
   encajar contratos. No inventes APIs; usa las que ya existen.
2. **Definir contrato.** Bosqueja la API pública del módulo (clases/firmas) en
   `FASE{N}_DESIGN.md` o en un comentario corto. Alineado con el grafo y Supervisor.
3. **Escribir el core.** El núcleo lo escribes tú (debe encajar con lo existente).
   Usa `write_file`/`patch`, no `echo`.
4. **Smoke antes de tests.** Valida con `uv run python -c "..."` ANTES de delegar
   tests formales. Corrige bugs de raíz, no síntomas.
5. **Delegar en PARALELO donde sea independiente.** Usa `delegate_task` con
   subagentes `leaf` para: (a) tests del módulo, (b) CLI del módulo. Ambos leen el
   core YA en disco y NO se importan entre sí (sin race). Pásales contexto completo
   (rutas, API real, estilo de `board.py`/`swarm.py`/`session.py`, comandos de verificación).
6. **Verificar.** `uv run pytest tests/` debe quedar verde (exit 0). Si un test
   asume semántica vieja del contrato que corregiste, ajusta el test al comportamiento
   correcto (documenta por qué). No re-ejecutes ciegamente si falla idéntico: cambia
   estrategia.
7. **Documentar.** Actualiza `FASE{N}_PROGRESS.md`, `INDEX.md`, `TASKS.md`,
   `ROADMAP.md`, `CHANGELOG.md` (y `README.md` Status si cambia fase). Marca lo
   entregado; deja claro lo pendiente.
8. **Reportar.** Resumen ejecutable: qué se entregó, verificación (pytest/cli),
   bugs de raíz corregidos, y el SIGUIENTE paso sugerido. Luego detente y espera
   instrucción (el usuario trabaja en modo "mañana seguimos").

---

## 6. Criterio de avance — Fase 5 (CERRADA)

CIERRE de la fase completa (YA CUMPLIDO):
- Un flujo crítico modelado como grafo con checkpoint se reanuda tras interrupción. (✅ graph/flows)
- Un group chat de 3 agentes resuelve una tarea en diálogo. (✅ chat: converge con TERMINATE)
- Un root agent enruta a specialists según la petición. (✅ root: router + root_handler)
- Session state persistente por tenant entre turnos integrado a board+session. (✅ session + root.route)
- `ciel flow run`, `ciel chat group` y `ciel root route` funcionan offline. (✅ verificado)
- Suite verde. (✅ 153 passed, 1 skipped)

## 7. Criterio de avance — Fase 6 (cuándo cerrarla)

CIERRE de Fase 6 cuando:
- `EventLoop` ejecuta una `Task` autónoma y, tras un reinicio (reanudación desde
  checkpoint en `MemoryStore`), continúa y la completa. (nuevo)
- Los reintentos exponenciales se activan ante fallo transitorio y la tarea
  eventualmente termina en éxito. (nuevo)
- `ciel loop run` funciona offline (echo provider / handlers locales). (nuevo)
- Cada pieza (agent / eventloop) tiene core + CLI + tests verdes y está documentada.
- Suite verde (153 + N tests de Fase 6).

Criterio PARCIAL (módulo a módulo): cada pieza se considera hecha cuando tiene
core + CLI + tests verdes y está documentada.

---

## 7.1 Criterio de avance — Fase 6 (CERRADA)

- `EventLoop` ejecuta una `Task` autónoma y, tras un reinicio (reanudación desde
  checkpoint en `MemoryStore`), continúa y la completa. (✅ `EventLoop.resume`)
- Los reintentos exponenciales se activan ante fallo transitorio y la tarea
  eventualmente termina en éxito. (✅ `EventLoop.run`)
- `ciel loop run` funciona offline (handlers locales). (✅ verificado)
- Cada pieza (agent / eventloop) tiene core + CLI + tests verdes y está documentada.
- Suite verde. (✅ 165 → 194 passed incl. Fase 7)

---

## 7.2 Criterio de avance — Fase 7 (CERRADA)

- Un usuario sin rol correcto es rechazado por `RBACEngine.check` (lanza
  `RBACError`); `OIDCVerifier` verifica un token JWT o avisa (`FeatureUnavailable`)
  si falta la dependencia. (✅ tests rbac)
- El trail de auditoría es inmutable: `HashChainAuditSink.verify()` devuelve `False`
  si se altera una línea del jsonl. (✅ tests audit)
- El costo por tenant se detiene al superar el presupuesto: `CostGovernor.check_budget`
  lanza `BudgetExceededError`. (✅ tests cost)
- Los secretos se resuelven por backend (Vault/K8s/env) sin hardcodearlos; `require`
  lanza `SecretError` si ausente. (✅ tests secrets)
- Cuotas transversales por tenant/usuario: `TenantRateLimiter.consume` lanza
  `RateLimitError` al agotar. (✅ tests ratelimit)
- `ciel rbac` / `ciel cost` funcionan offline. (✅ verificado)
- Suite verde. (✅ 194 passed, 1 skipped)

---

## 10. Preparación Fase 8 (Deploy HA + observabilidad + madurez)

Esta sección PREPARA la siguiente sesión. Fase 8 NO está empezada; aquí está el
mapa de lo que existe y lo que hay que añadir, para no reimplementar.

### 10.1 Inventario de lo reutilizable (ya en el repo)
- **Helm base**: `deploy/helm/ciel/` — `Chart.yaml`, `values.yaml`,
  `templates/deployment.yaml` (Deployment + Service + PVC audit + probes
  liveness/readiness en `/health`), `_helpers.tpl`. Hoy `replicaCount` es 1 y NO
  tiene PDB/HPA/anti-affinity. Es el punto de partida para HA.
- **OTel**: `src/ciel/observability/otel.py` (ya emite trazas) y
  `src/ciel/observability/metrics.py` (Prometheus counters). Reutilizar, no duplicar.
- **Audit inmutable**: `src/ciel/enterprise/audit.py::HashChainAuditSink` (Fase 7) —
  la capa de observabilidad HA debe leer/exportar desde aquí.
- **Gateway**: `src/ciel/gateway/` (MCP/ACP/adapter, `server.py` compuesto con
  `mount`). Los middlewares transversales de Fase 7 (`enterprise.rbac`,
  `enterprise.cost`, `enterprise.ratelimit`) se enchufan aquí.
- **Adapters hoy**: Webhook + Slack (en gateway). Faltan Teams/Discord/Web UI.
- **Grafo**: `src/ciel/orchestration/graph.py` — `GraphRunner.run/resume`,
  `GraphNode`, `GraphState`. El HIL se implementa como interrupt en el nodo.

### 10.2 Qué falta (checklist de Fase 8)
1. **Helm HA** (`deploy/helm/ciel/templates/`): `poddisruptionbudget.yaml`
   (`minAvailable: 2` o `maxUnavailable: 1`), `hpa.yaml`
   (`HorizontalPodAutoscaler` sobre `metrics` requests/CPU; requiere
   `metrics-server` en el cluster), `affinity` anti-affinity en `deployment.yaml`,
   `topologySpreadConstraints`. Subir `replicaCount` por defecto a 2–3.
2. **OTel centralizado** (`src/ciel/observability/otel_collector.py` o flag
   `--otel` en `ciel serve`): exportador OTLP a collector; tests que verifiquen
   que se emiten spans sin red (exportador en memoria/in-memory span processor).
3. **Adapters** (`src/ciel/adapters/`): `TeamsAdapter`, `DiscordAdapter`,
   `WebUIAdapter` con interfaz común (`send`/`receive`, fakes offline en tests).
   Cablear en `ciel chat`/`ciel flow`.
4. **HIL** (`src/ciel/orchestration/graph.py`): `GraphNode(require_approval=...)`;
   `GraphRunner` pausa y persiste estado en `GraphCheckpointStore`; `resume` tras
   aprobación. Integración con `enterprise.rbac.check(action="approve:*")`.
5. **Runbooks** (`docs/runbooks/`): deploy, incidente, rollback, backup
   audit/board, escalado HPA.
6. **Release v0.2.0**: tag + wheels + CHANGELOG (sección "## [0.2.0]"); doc upgrade.
7. **Smoke HA** (opcional): `ciel serve` con N réplicas; verificar health + checkpoint
   compartido (SQLite compartido o backend de checkpoint remoto — NOTA: el
   `MemoryStore` es local por tenant; para HA real el checkpoint debe ser compartido
   vía `MemoryStore` sobre SQLite montado en PVC o Postgres; decidir en FASE8_DESIGN).

### 10.3 Criterio de avance — Fase 8 (cuándo cerrarla)
- El chart despliega N≥2 réplicas con PDB + HPA y sobrevive a la caída de 1 réplica
  (health + reanudación de checkpoint). 
- OTel envía traces/metrics a un collector (o in-memory en tests) sin romper offline.
- `ciel chat`/`ciel flow` reciben/emiten por Teams/Discord/Web UI (fakes en tests).
- Un nodo de grafo con `require_approval` pausa y reanuda tras aprobación de un rol
  autorizado (`approve:*`).
- Runbooks documentados; release v0.2.0 etiquetado.
- Suite verde (194 + N tests de Fase 8).

### 10.4 Documentación a crear en Fase 8
- `docs/dev/FASE8_DESIGN.md` (decisión de backend de checkpoint compartido para HA,
  contrato de adapters, diseño HIL).
- `docs/dev/FASE8_PROGRESS.md`.
- Actualizar `TASKS.md`, `docs/ROADMAP.md`, `CHANGELOG.md`, `README.md`, `INDEX.md`.

---

## 8. Comandos de verificación (copiar/pegar)

```bash
cd A:/Apps/Agents/ciel-agent-framework
uv run pytest tests/            # esperado: 194 passed, 1 skipped (base Fase 5 + 41 Fase 6/7)
uv run ciel graph demo         # grafo demo offline (Fase 5)
uv run ciel flow run           # flow event-driven demo offline (Fase 5)
uv run ciel chat group         # group chat de 3 agentes que converge offline (Fase 5)
uv run ciel root route "SELECT * FROM users" --db /tmp/s.db --session-id s1 --tenant t1  # root routing offline + session state
uv run ciel serve              # app compuesta (control + MCP + webhook)
uv run ciel swarm run          # orquestación desde AgentSpec YAML
uv run ciel board list         # tablero kanban (SQLite vía CIEL_BOARD_DB)
uv run ciel loop run "resume tras reinicio" --db /tmp/l.sqlite3 --tenant t1  # agente autónomo en bucle offline (Fase 6)
uv run ciel loop resume --run-id <id> --db /tmp/l.sqlite3  # reanuda loop tras reinicio (Fase 6)
uv run ciel rbac list-roles    # roles y permisos RBAC (Fase 7, offline)
uv run ciel rbac check --subject bob --action agent:run  # verifica permiso (Fase 7; exit 1 si deniega)
uv run ciel cost status --tenant t1  # gasto/presupuesto por tenant (Fase 7, offline)
uv build                       # genera wheels en dist/
```

---

## 9. Notas de contexto

- El repo NO tiene git inicializado (estado se mantiene en disco; no hay commits).
  Si se inicializa git, el primer commit debe incluir todo el árbol.
- `generate_tasks.py` regenera un borrador de `TASKS.md` (hasta Fase 4); la
  versión canónica es `TASKS.md` en la raíz (incluye Fase 5+). No creer ciegamente
  a `generate_tasks.py`: Fases 0–5 ya están CERRADAS (ver CHANGELOG/CIERRE_SESION).
- El usuario prefiere español para comunicación y docs; desarrollo autónomo
  manos-off, ejecutable sobre planificación extendida.
- Al delegar a subagentes, pasar SIEMPRE rutas absolutas y la API real del core;
  los subagentes no ven esta conversación. Windows: al borrar dbs SQLite temporales
  en tests, cerrar `store.conn` (o `mem.conn`) antes de `os.remove` para liberar el lock.



# ultimo
Resumen de Fase 8 (Ciel Agent Framework) — estado actual


🔄 MCP server config changed — reloading connections...
     Trabajo completado y verificado con smoke tests:
🔄 Reloading MCP servers...
  No MCP servers connected.
     - FASE8_DESIGN.md: decisiones de backend checkpoint compartido (HA), contrato adapters, diseño HIL.
     Documentado en docs/dev/.
     - Helm HA: PDB, HPA (metrics + behavior), anti-affinity y topologySpreadConstraints condicionales,
     replicaCount >= 2. Chart 0.2.0. (helm no instalado en entorno; validación documentada en runbooks como helm
     template/helm lint.)
     - ciel.adapters: TeamsAdapter, DiscordAdapter, WebUIAdapter + FakeAdapter (offline-safe, sin red). Contrato
     sobre el MessagingAdapter existente.
     - Routers de gateway: create_teams_webhook_router, create_discord_webhook_router, create_webui_router en
     ciel/gateway/messaging.py; montados en make_app (ciel serve) y exportados en gateway/init.py.
     - HIL en grafo: GraphNode.require_approval, GraphPaused, GraphApprovalDenied, GraphRunner.approve()/deny() con
     chequeo RBAC. Falso positivo corregido: role admin ahora incluye approve:* (Fase 7 intacta). Smoke test
     confirmó: pausa en nodo deploy, deny funciona, alice (admin) aprueba y ejecuta, bob (viewer) es bloqueado por
     RBACError.
     - OTel centralizado: flag --otel / --otel-endpoint en ciel serve, comando ciel observe, init_tracing con OTLP
     o InMemorySpanExporter, current_tracer(), span_count(). CLI serve --help y observe verificados.

     Pendiente / issues conocidos:
     1. span_count() devuelve -1 en lugar del conteo real. Causa: el atributo del exporter in-memory no coincide
     con provider.active_span_processor.span_exporter (el TracerProvider real usa _active_span_processor o
     estructura distinta en opentelemetry-sdk 1.x). Hay que inspeccionar la estructura real del provider para
     extraer el InMemorySpanExporter. No rompe la compilación ni los demás features, pero el test de conteo de
     spans fallaría hasta corregirlo.
     2. Runbooks docs/runbooks (deploy, incidente, rollback, backup audit/board, HPA) — no iniciado.
     3. Tests formales Fase 8 (adapters, HIL, otel) + CLI — no escritos aún.
     4. Docs: FASE8_PROGRESS.md, INDEX, TASKS, ROADMAP, CHANGELOG, README Status — no iniciados.
     5. Release v0.2.0 (tag + wheels) — pendiente.
     6. Regresión completa: uv run pytest tests/ verde + smoke CLI — aún no corrida tras estos cambios.

     Siguiente paso sugerido (cuando retomes): corregir span_count() inspeccionando la estructura real de
     TracerProvider (usar provider._active_span_processor o provider.get_active_span_processor().span_exporter),
     luego escribir los tests Fase 8 y correr la regresión completa antes de los runbooks y el release.

     Nota: no he corrido uv run pytest tests/ tras los cambios de esta sesión, así que no afirmo que la suite
     completa esté verde; los smoke tests puntuales de HIL/adapters/CLI sí pasaron.

 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

## 9. PENDIENTE PARA LA TARDE / SIGUIENTE SESIÓN (Fase 9 en curso)

Fecha: 2026-07-14 (tarde). Lo avanzado hasta ahora en la Fase 9 está commiteado
en `13af11b` (core) y subido a GitHub. Lo que sigue:

### 9.1 Estado verificado de la Fase 9 (commit 13af11b, ya en GitHub)
- `ciel.plugins`: PluginRegistry + default_registry() (builtins + entry points).
- `ciel.providers.gemini`: GeminiProvider (builtin con OpenAI/Anthropic).
- `ciel.runtime.tools_builtins`: toolset `builtins` (echo, datetime, http_get, file_read, shell).
- `ciel init`: scaffold offline-safe e idempotente (genera proyecto que corre sin red).
- Bug fix: ToolRegistry.register_tool sincroniza ToolsetSchema.tools.
- Tests Fase 9: 13 nuevos (8 plugins + 5 tools). Regresión: 228 passed, 2 skipped.
- `docs/guide/*.md` (9 archivos) + `mkdocs.yml` ESCRITOS pero aún NO commiteados.
- `examples/quickstart_agent.py` reescrito para correr offline.

### 9.2 BUG CONOCIDO QUE QUEDÓ A MEDIAS (prioridad 1 al retomar)
`examples/quickstart_agent.py` corre pero `tool=add output=None` → OK=False.
Causa raíz ya aislada: `ToolProvider.execute` (src/ciel/runtime/tools.py ~l64)
NO ejecutaba el callable (devolvía placeholder). Ya se corrigió para invocar
`tool.callable_(arguments, tool_call_id=..., tenant_id=...)` con manejo de
async/excepciones. TRAS el fix, el output sigue saliendo None → el runtime
(`DefaultAgentRuntime.run_agent_loop`) probablemente NO pasa por
`DefaultToolDispatcher.dispatch`, sino por otro camino (quizá
`TenantAwareToolProvider.execute(context=...)` o invoca el callable con firma
distinta). Pasos exactos para cerrar:
  1. Leer `DefaultAgentRuntime.run_agent_loop` (buscar en src/ciel/runtime/agent*.py
     o donde esté) y ver CÓMO ejecuta los `tool_calls` del provider (¿usa
     dispatcher.dispatch / dispatch_all, o provider.execute con context?).
  2. Alinear la firma del callable del example (`def add(arguments, *, tool_call_id, tenant_id) -> ToolResult`)
     con lo que espera ese camino. El contrato oficial documentado en docs/guide/tools.md
     es `callable_(arguments: dict, *, tool_call_id, tenant_id) -> ToolResult|dict`.
  3. Verificar: `uv run examples/quickstart_agent.py` debe salir exit 0 con OK=True.
  4. Añadir test formal de dispatch end-to-end (runtime + dispatcher + tool real)
     en tests/test_fase9_tools_test.py para evitar regresión de este bug.

### 9.3 Tareas pendientes de la Fase 9 (checklist)
- [ ] Cerrar bug de ejecución de tool vía runtime (9.2).
- [ ] Commit de `docs/guide/` + `mkdocs.yml` + `examples/quickstart_agent.py` (fix) → commit "Fase 9 (docs): guía DX externa + mkdocs + example offline".
- [ ] Regresión completa `uv run pytest tests/` verde tras el fix de tools.py.
- [ ] `ciel doctor` / smoke: `uv run ciel init /tmp/x && correr agente`.
- [ ] Tag v0.3.0 + (opcional) publicar en PyPI `mana-ciel` v0.3.0 (requiere token; el job de GH Actions release.yml tiene publish comentado — descomentar + secret CIEL_PYPI_TOKEN).
- [ ] CHANGELOG 0.3.0: mover de "EN PROGRESO" a cerrado; añadir sección de bug fix de ToolProvider.execute.
- [ ] TASKS.md / INDEX.md / FASE9_PROGRESS.md: marcar Fase 9 CERRADA.

### 9.4 Notas de contexto para no perder el hilo
- El subagente de documentación DX TIMEOUT (600s) sin entregar; por eso docs/guide
  los escribí yo manualmente. No reintentar subagente para esto.
- mkdocs-material está en el extra `docs` de pyproject (no requiere install extra para leer .md; solo para `mkdocs build`).
- El token PyPI usado para v0.2.0 NO se guardó; para v0.3.0 pedirlo de nuevo o usar el secret de GitHub.
- Convención: imports `ciel`, CLI `ciel`, paquete PyPI `mana-ciel`, repo `Ander-Labs/ciel-agent-framework`.

⚠ Iteration budget reached (60/60) — response may be incomplete
  ✅ Agent updated — 33 tool(s) available
  💾 Self-improvement review: Patched SKILL.md in skill 'ciel-agent-framework-dev' (1 replacement). · Memory updated

  