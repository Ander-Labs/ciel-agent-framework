# FASE 8 — Deploy HA + observabilidad + madurez (PROGRESO)

Fecha de arranque: 2026-07-13. Última actualización: 2026-07-14.

Estado: **CERRADA**. Todo el código de las piezas está entregado, verificado por
smoke tests y por la regresión completa. Release **v0.2.0 etiquetado** (tag git
`v0.2.0`). La continuación Fase 9 (release **v0.3.0**) ya está **publicada en
PyPI** (`pip install mana-ciel==0.3.0`). Ver también `docs/dev/FASE8_DESIGN.md`
(diseño) y `docs/runbooks/` (deploy/incident/rollback/backup/hpa).

## Entregado y verificado

### 8.1 Helm HA
- `deploy/helm/ciel`: `replicaCount: 2` por defecto (N≥2).
- `templates/poddisruptionbudget.yaml`: PDB con `minAvailable: 1` (sobrevive a la
  caída de 1 réplica sin down total).
- `templates/hpa.yaml`: `HorizontalPodAutoscaler` (min 2 / max 10 réplicas,
  target CPU 70%).
- `deployment.yaml`: `podAntiAffinity` (topologyKey `kubernetes.io/hostname`) y
  `topologySpreadConstraints` (maxSkew 1, ScheduleAnyway).
- `values.yaml` expone `ha.*` (pdb/hpa/anti-affinity/topologySpread).
- Validación documentada en `docs/runbooks/deploy.md` (`helm lint` /
  `helm template`). helm no instalado en el entorno local.

### 8.2 OTel centralizado (bug de `span_count` ya corregido)
- `ciel.observability.otel.init_tracing(*, otlp_endpoint)`: usa
  `InMemorySpanExporter` por defecto (offline-safe) o `OTLPSpanExporter` si hay
  endpoint. Fija la referencia global `_last_provider`.
- `span_count()` **corregido** para opentelemetry-sdk 1.x: navega
  `provider._active_span_processor._span_processors[].span_exporter` en lugar de
  los atributos inexistentes `active_span_processor`/`span_exporter` del provider.
  Devuelve el nº de spans del `InMemorySpanExporter` (o `-1` si no aplica).
- `current_tracer()` devuelve el tracer global.
- `ciel observe` (CLI, Typer+Rich) + flag `--otel`/`--otel-endpoint` en `ciel serve`.
- Smoke verificado: `init_tracing()` + `start_as_current_span` → `span_count() >= 1`.

### 8.3 Adapters de canal (Teams / Discord / Web UI)
- `ciel.adapters`: `TeamsAdapter`, `DiscordAdapter`, `WebUIAdapter` +
  `FakeAdapter` (offline-safe). Heredan `MessagingAdapter`/`Message` de
  `ciel.gateway.adapter` (runtime-agnostic, sin FastAPI).
- `TeamsAdapter`/`DiscordAdapter` usan `httpx` para `send` (POST JSON a webhook);
  reciben vía router. `WebUIAdapter` colas en memoria. `FakeAdapter` colas
  `asyncio.Queue` para tests sin red.

### 8.4 Routers de gateway (messaging)
- `ciel.gateway.messaging`: `create_teams_webhook_router`,
  `create_discord_webhook_router`, `create_webui_router`. Montados en
  `make_app` (`ciel serve`) y exportados en `ciel.gateway.__init__`.
- Health endpoints `/v1/messaging/{teams,discord,webui}/health` verificados (200).

### 8.5 Human-in-the-loop (HIL) en grafo
- `GraphNode.require_approval: Optional[str]` (p. ej. `"approve:deploy"`).
- `GraphRunner.run` pausa ANTES del nodo y persiste `paused=True`/`paused_node`.
  Lanza `GraphPaused(node_id, action, run_id)`.
- `GraphRunner.approve(run_id, *, approver, rbac, action)` reanuda; si `rbac`
  pasado, valida `rbac.check(approver, action, tenant_id=...)` → `RBACError` si
  no autorizado. Tras aprobar ejecuta el nodo y continúa (no re-ejecuta previos).
- `GraphRunner.deny(run_id, *, reason)` lanza `GraphApprovalDenied` y persiste
  `paused=False`.
- Integración RBAC: el grafo recibe `RBACEngine` como parámetro en `approve`
  (no acopla `enterprise` en import-time).
- Smoke verificado: pausa en nodo deploy; bob (viewer) bloqueado por RBACError;
  alice (admin, con `approve:*`) aprueba y el grafo completa.

## Bugs de raíz corregidos

### Del Prompt.md sección 2 (ya corregidos, no reintroducir)
1. **`ciel.runtime.memory.MemoryStore` + `tenant_id=None`**: insertaba filas
   duplicadas (SQLite no trata dos `NULL` como iguales para `UNIQUE`). Corregido
   normalizando `tenant_id=None` a sentinel `__none__` en `set`/`get`/`delete`/
   `record_tool_execution`. Afectaba checkpoints/board offline en TODO el framework.
2. **`GraphRunner.resume`**: retomaba desde el nodo *siguiente* al último
   completado (antes re-ejecutaba el último nodo, duplicándolo).
3. **`GraphRunner._run_node`**: ahora acepta funciones de nodo síncronas o async.
4. **`FlowRunner._ready`**: ya no activa ramas (`add_branch`) sin fuente como si
   fueran `start`; una rama sólo se ejecuta cuando un router la activa explícitamente.
5. **`add_router`**: valida destinos contra pasos ya registrados en `compile()`;
   se añadió `add_branch` para registrar ramas de forma explícita (elimina el
   orden frágil de registro en tiempo de definición).
6. **`RootState.history`**: el campo `history` (turnos previos de session) se
   incluye SIEMPRE en `snapshot()`/`from_snapshot()`; no quitarlo ni romper el
   round-trip de session state (agregado en el cierre de Fase 5).

### De Fase 8
- **Rol `admin` ahora incluye `approve:*`**: el HIL requiere que el aprobadador
  tenga el permiso `approve:*` (wildcard `category:*`). El `RBACEngine` se
  corrigió para que el rol `admin` por defecto cubra `approve:*` (antes el rol
  admin no lo incluía y el HIL denegaba incluso a administradores). Verificado:
  `alice` (admin) aprueba; `bob` (viewer) es bloqueado por `RBACError`.
- **`ciel.observability.otel.span_count()` devolvía `-1` siempre**: (a) `init_tracing`
  no guardaba `_last_provider` (falta `global`); (b) accedía a
  `provider.active_span_processor`/`span_exporter` que no existen en
  opentelemetry-sdk 1.x. Corregido con `_find_in_memory_exporter` que navega
  `_active_span_processor._span_processors[].span_exporter`.

## Pendiente / estado de release
- **Release v0.2.0: ETIOUETADO** ✅. Tag git `v0.2.0` creado; wheels en `dist/`;
  CHANGELOG con sección `## [0.2.0]`; doc de upgrade desde v0.1.0.
- **Release v0.3.0 (Fase 9): PUBLICADO EN PyPI** ✅. `pip install mana-ciel==0.3.0`
  (distribución `mana-ciel`, import `ciel`). Verificado install limpio +
  `default_registry().list_providers()` expone openai/anthropic/gemini + toolset
  `builtins`. Tag git `v0.3.0` también presente.

## Criterio de avance (sección 10.3 del Prompt.md)
- Chart N≥2 réplicas + PDB + HPA, sobrevive a caída de 1. ✅ chart + PDB/HPA listos.
- OTel envía traces/metrics sin romper offline. ✅ in-memory + flag `--otel`.
- `ciel chat`/`ciel flow` por Teams/Discord/Web UI (fakes en tests). ✅ adapters+routers.
- Nodo `require_approval` pausa y reanuda tras aprobación `approve:*`. ✅ core + tests.
- Runbooks documentados. ✅ `docs/runbooks/` (deploy/incident/rollback/backup/hpa).
- Release v0.2.0 etiquetado. ✅ tag `v0.2.0`.
- Release v0.3.0 (Fase 9) publicado en PyPI. ✅ `mana-ciel==0.3.0`.
- Suite verde (194 + N). ✅ **230 passed, 2 skipped** (base F0–8 = 216 + 14 Fase 9).
