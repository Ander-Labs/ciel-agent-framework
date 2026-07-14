# Pendientes y gap analysis — estado al cierre de Fase 8 (v0.2.0)

Última actualización: 2026-07-14. Estado base: **Fase 8 EN PROGRESO → cerrada
salvo tag git**. Suite verde: **216 passed, 1 skipped**. Release v0.2.0 (wheels
+ CHANGELOG); tag pendiente de push a GitHub por el usuario.

Este documento es el gap analysis de lo que FALTA tras Fases 0–8 y del roadmap
extendido aún no abordado.

## 1. Estado por fase (verificado en disco)

| Fase | Estado | Nota |
|------|--------|------|
| 0–4 | ✅ Cerradas | Fundación, runtime, gobierno, multiagente, superficies/deploy |
| 5 | ✅ Cerrada | graph / flows / chat / root / session |
| 6 | ✅ Cerrada | agent: EventLoop + AutonomousAgent |
| 7 | ✅ Cerrada | enterprise: rbac/oidc, audit inmutable, cost, secrets, ratelimit |
| 8 | 🔶 Casi cerrada | Helm HA, OTel, adapters, HIL, runbooks, tests ✅; tag git pendiente |

## 2. Lo que YA existe (reutilizable, no reimplementar)

- `ciel.gateway.auth`: API-key opcional (Bearer/X-API-Key, `hmac.compare_digest`).
  Hoy es candado de transporte, NO RBAC/OIDC de aplicación (el RBAC de Fase 7 vive
  en `ciel.enterprise.rbac` y aún no está cableado como middleware de authn en el
  gateway — ver sección 3).
- `ciel.observability.metrics`: counters Prometheus (`ciel_requests_total`,
  `ciel_tool_calls_total`, `ciel_agent_loops_total`) con label `tenant`.
- `ciel.observability.audit` + `ciel.enterprise.audit.HashChainAuditSink`: audit
  inmutable hash-chained (SOC2-ready) ya entregado en Fase 7.
- `deploy/helm/ciel`: HA (PDB/HPA/anti-affinity/topologySpread), `replicaCount: 2`.
- `ciel.adapters` + `ciel.gateway.messaging`: Teams/Discord/WebUI + routers.

## 3. Gaps reales tras Fase 8 (lo que falta)

### 3.1 Cableado transversal (alto valor, bajo esfuerzo)
- [ ] **Middleware RBAC en gateway**: `ciel.enterprise.rbac` existe pero el gateway
  aún no lo aplica por ruta (solo API-key transport en `auth.py`). Cablear
  `RBACEngine.check` en `make_app` para acciones por endpoint.
- [ ] **Cost governance en requests**: `CostGovernor` (Fase 7) existe pero el
  gateway no lo consulta antes de ejecutar (corte por presupuesto de modelo).
- [ ] **Rate-limit transversal**: `TenantRateLimiter` (Fase 7) existe pero no está
  montado como middleware del gateway.
- [ ] **OTel como middleware de request**: `init_tracing` + `OtlpAuditExporter`
  existen; falta spans automáticos por request en el gateway (hoy emisión manual).

### 3.2 Smoke/validación HA (opcional, no bloquea)
- [ ] **Smoke HA**: `ciel serve` con N réplicas vía compose/uv; verificar health +
  checkpoint compartido. Requiere backend de checkpoint compartido (RWX o Postgres)
  — ver `docs/dev/FASE8_DESIGN.md` sección 1 (hoy SQLite local por réplica).
- [ ] **helm lint/template en CI**: validar el chart automáticamente.

### 3.3 Frente paralelo "Runtime evolutivo + datos" (diferenciador, sin tocar)
- [ ] `ciel.runtime.skills`: skills que se REFINAN solas (aprendizaje procedimental:
  versión, métricas de éxito, rollback).
- [ ] `ciel.runtime.codex`: Code Execution en sandbox (ADK) sobre `ciel.sandbox`.
- [ ] `ciel.runtime.rag`: Knowledge base / RAG como TOOL (LlamaIndex), no acoplado
  al core; `ciel.runtime.knowledge` ingestión/indexación/recuperación pluggable
  (vector store por tenant).
- [ ] CLI: `ciel skills tune`, `ciel rag ingest`, `ciel run --codex`.

### 3.4 Pulidos de release
- [ ] **Tag git v0.2.0** + push a GitHub (el usuario lo ejecuta; repo inicializado
  y commiteado localmente en esta sesión, sin push).
- [ ] **Doc de upgrade v0.1.0 → v0.2.0** (cambios de Helm values: `replicaCount`,
  `ha.*`; nuevo flag `--otel`; nuevos adapters/routers).

## 4. Resumen ejecutivo — qué falta por terminar
1. **Cableado transversal Fase 7→gateway** (RBAC/cost/ratelimit/OTel como middleware):
   el valor enterprise ya está implementado como librería; falta enchufarlo al gateway.
2. **Smoke HA opcional**: validar N réplicas + checkpoint compartido.
3. **Frente paralelo evolutivo/RAG/codex**: diferenciador del framework, aún sin tocar.

Siguiente paso recomendado: cablear `RBACEngine`/`CostGovernor`/`TenantRateLimiter`
como middlewares del gateway (reusar lo ya entregado, sin reimplementar), y luego
abrir el frente RAG/codex.
