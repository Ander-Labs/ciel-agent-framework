# FASE 8 — Deploy HA + observabilidad + madurez (PROGRESO)

Fecha de arranque: 2026-07-13. Última actualización: 2026-07-14.

Estado: **EN PROGRESO**. El código de todas las piezas está entregado y
verificado por smoke tests. Pendiente: tests formales (en curso vía subagentes),
regresión completa, runbooks (HECHOS) y release v0.2.0.

## Entregado y verificado (smoke)

### 8.1 Helm HA
- `deploy/helm/ciel`: `replicaCount: 2` por defecto.
- `templates/poddisruptionbudget.yaml`: PDB con `minAvailable: 1`.
- `templates/hpa.yaml`: `HorizontalPodAutoscaler` (min 2 / max 10, target CPU 70%).
- `deployment.yaml`: `podAntiAffinity` (preferred, `kubernetes.io/hostname`) y
  `topologySpreadConstraints` (maxSkew 1, ScheduleAnyway).
- `values.yaml` expone `ha.*` (pdb/hpa/anti-affinity/topologySpread).
- Validación documentada en `docs/runbooks/runbook_deploy.md` (`helm lint` /
  `helm template`). helm no instalado en el entorno local.

### 8.2 OTel centralizado (CORREGIDO el bug de `span_count`)
- `ciel.observability.otel.init_tracing(*, otlp_endpoint)`: usa
  `InMemorySpanExporter` por defecto (offline-safe) o `OTLPSpanExporter` si hay
  endpoint. Fija la referencia global `_last_provider` (antes asignaba a variable
  local → `span_count` siempre veía `None`).
- `span_count()` **corregido** para opentelemetry-sdk 1.x: navega
  `provider._active_span_processor._span_processors[].span_exporter` en lugar de
  los atributos inexistentes `active_span_processor`/`span_exporter` del provider.
  Devuelve el nº de spans del `InMemorySpanExporter` (o `-1` si no aplica).
- `current_tracer()` devuelve el tracer global.
- `ciel observe` (CLI, Typer+Rich) + flag `--otel`/`--otel-endpoint` en `ciel serve`.
- Smoke verificado: `init_tracing()` + `start_as_current_span` → `span_count() >= 1`.

### 8.3 Adapters (Teams / Discord / Web UI)
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

## Bugs de raíz corregidos en Fase 8
1. `ciel.observability.otel.span_count()` devolvía `-1` siempre: (a) `init_tracing`
   no guardaba `_last_provider` (falta `global`); (b) accedía a
   `provider.active_span_processor`/`span_exporter` que no existen en
   opentelemetry-sdk 1.x. Corregido con `_find_in_memory_exporter` que navega
   `_active_span_processor._span_processors[].span_exporter`.

## Pendiente
- [ ] Release v0.2.0: tag + wheels + CHANGELOG `## [0.2.0]` + doc upgrade.
  (Suite ya verde: 216 passed, 1 skipped. El repo no tiene git inicializado;
  el tag requiere inicializar git — confirmar con el usuario.)

## Criterio de avance (sección 10.3 del Prompt.md)
- Chart N≥2 réplicas + PDB + HPA, sobrevive a caída de 1. ✅ chart listo.
- OTel envía traces/metrics sin romper offline. ✅ in-memory + flag `--otel`.
- `ciel chat`/`ciel flow` por Teams/Discord/Web UI (fakes en tests). ✅ adapters+routers.
- Nodo `require_approval` pausa y reanuda tras aprobación `approve:*`. ✅ core + tests.
- Runbooks documentados. ✅ `docs/runbooks/`.
- Release v0.2.0 etiquetado. ⏳ pendiente (tag git requiere init).
- Suite verde (194 + N). ✅ **216 passed, 1 skipped** (22 tests Fase 8).
