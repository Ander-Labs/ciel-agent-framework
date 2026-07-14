# FASE 8 — Deploy HA + observabilidad + madurez de producción

Fecha de diseño: 2026-07-13. Fase 8 NO empezada antes de esta sesión. Este
documento fija las decisiones de arquitectura para no reimplementar lo que ya
existe (ver `docs/Prompt.md` sección 10.1).

## 1. Backend de checkpoint compartido para HA

El `MemoryStore` es local-por-proceso (SQLite en disco, un archivo por
instancia). Para HA real con N≥2 réplicas que sobrevivan a la caída de 1
réplica, el checkpoint debe ser **compartido**.

**Decisión:** soportar dos modos, sin romper el contrato existente de
`MemoryStore`:

1. **Modo PVC compartido (por defecto en Helm HA).** El chart monta el mismo
   volumen `ReadWriteMany` (o un `ReadWriteOnce` con un StatefulSet/aliado a
   un backend compartido) para la base de audit/board y los checkpoints. Como
   el `MemoryStore` ya escribe SQLite en ruta configurable, basta montar el
   directorio de checkpoint en un volumen compartido. Esto es OFFLINE-SAFE y
   no requiere nuevas dependencias.
   - Limitación conocida: SQLite con `RWMany` tiene concurrencia limitada.
     Para carga alta se recomienda Postgres (ver modo 2), pero no es
     obligatorio para el criterio de avance Fase 8 (sobrevive a 1 réplica).
2. **Modo Postgres (opcional, futuro).** Dejar `MemoryStore` con un `_backend`
   inyectable para Postgres. NO se implementa en esta fase; se documenta el
   punto de extensión en `docs/runbooks/`.

La `GraphCheckpointStore` / `FlowCheckpointStore` / `EventLoopCheckpointStore`
ya usan `(tenant_id, session_id, key)` sobre `MemoryStore`, así que compartir
el archivo SQLite es suficiente para la reanudación tras caída de réplica.

## 2. Contrato de adapters (messaging)

Reutilizar `ciel.gateway.adapter.MessagingAdapter` (base abstracta con
`receive()` async generator y `send(Message)`). Hoy existen `WebhookAdapter`
(inbound-only) y `SlackAdapter` (bidireccional, `slack_sdk` lenient). La fase 8
añade en `ciel.adapters` (nuevo paquete, independiente de FastAPI para tests):

- `TeamsAdapter(MessagingAdapter)`: `send` a Microsoft Teams vía webhook
  entrante (payload `{"text": ...}` a una *Incoming Webhook* URL); `receive`
  vía un router de webhook que enqueuea (igual patrón que `SlackAdapter`).
  OFFLINE-SAFE: sin SDK duro, usa `httpx` (ya dependencia base) para `send`;
  `receive` alimentado por el router.
- `DiscordAdapter(MessagingAdapter)`: `send` a un canal Discord vía webhook
  `https://discord.com/api/webhooks/<id>/<token>` (POST JSON `{"content": ...}`);
  `receive` vía gateway router que enqueuea eventos `MESSAGE_CREATE`.
- `WebUIAdapter(MessagingAdapter)`: adapter en memoria para la Web UI. `send`
  escribe a una cola pública que la UI sondea; `receive` lee de una cola de
  entrada. Totalmente offline (sin red).
- `FakeAdapter(MessagingAdapter)`: adapter de prueba que implementa `send` y
  `receive` sobre colas `asyncio.Queue` internas, sin red. Usado por los tests
  de Fase 8 (cumple "fakes en tests, offline-safe").

Todos los adapters heredan `Message`/`MessagingAdapter` y son runtime-agnostic
(como `WebhookAdapter`). El gateway los monta vía routers FastAPI nuevos
(`create_teams_webhook_router`, `create_discord_webhook_router`,
`create_webui_router`) en `ciel.gateway`, y `ciel chat`/`ciel flow` ganan una
bandera `--adapter` opcional **solo para demos offline** (usa `FakeAdapter`).

## 3. Diseño HIL (Human-in-the-loop) en el grafo

Reutilizar `ciel.orchestration.graph` (LangGraph-style, sobre `Supervisor`).
El interrupt es un atributo del nodo:

- `GraphNode.require_approval: Optional[str]` — acción RBAC requerida para
  aprobar (p. ej. `"approve:deploy"`). Si se define, `GraphRunner` pausa ANTES
  de ejecutar el nodo y persiste un checkpoint de "pendiente de aprobación"
  (`paused=True`).
- `GraphRunner.approve(run_id, *, approver, rbac=None, action=None)` — reanuda
  el nodo pausado. Si `rbac` se pasa (un `RBACEngine`), valida que `approver`
  tenga el permiso `action` (por defecto `require_approval`). Si no tiene
  permiso, lanza `RBACError` (reutiliza `ciel.enterprise.rbac`). Tras aprobar,
  ejecuta el nodo y continúa el grafo normalmente.
- `GraphRunner.deny(run_id, *, approver, reason)` — marca el nodo como
  denegado y detiene el grafo (lanza `GraphApprovalDenied`).
- El checkpoint guarda `paused_node` y `paused=True` para poder rehidratar y
  continuar tras reinicio (igual patrón que `resume`).

Contrato de integración RBAC: el grafo NO acopla `RBACEngine`; lo recibe como
parámetro en `approve`. Esto mantiene `orchestration` libre de depender de
`enterprise` en import-time (solo en runtime, igual que `CostGovernor` es
capa transversal).

## 4. OTel centralizado

Reutilizar `ciel.observability.otel.init_tracing` (ya crea `TracerProvider`
con `InMemorySpanExporter` por defecto, y OTLP si hay endpoint). La fase 8:

- Añade `ciel.observe` (CLI) y un flag `--otel [endpoint]` en `ciel serve`.
  Sin endpoint → in-memory (offline-safe). Con endpoint → `OTLPSpanExporter`.
- Añade `ciel.observability.otel.span_count()` helper para tests: devuelve el
  número de spans emitidos por el exporter in-memory (accede al exporter vía
  el provider). Los tests verifican que los spans se emiten sin red.
- El gateway (control + MCP + webhook) emite un span por request usando
  `OtlpAuditExporter` (ya existe) o `ToolAwareTracer` (ya existe) — no se
  duplica lógica.

## 5. Runbooks

`docs/runbooks/`: deploy (Helm HA), incidente, rollback (Helm `--revision` /
`helm rollback`), backup de audit/board (SQLite en PVC), escalado HPA.

## 6. Criterio de avance (resumen)

1. Chart despliega N≥2 réplicas con PDB + HPA y sobrevive a la caída de 1.
2. OTel envía traces/metrics (o in-memory en tests) sin romper offline.
3. `ciel chat`/`ciel flow` reciben/emiten por Teams/Discord/Web UI (fakes en tests).
4. Nodo de grafo `require_approval` pausa y reanuda tras aprobación de rol
   autorizado (`approve:*`).
5. Runbooks documentados; release v0.2.0 etiquetado.
6. Suite verde (194 + N tests de Fase 8).
