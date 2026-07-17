# Runbook: Incidente

Procedimiento ante incidentes en producción de Ciel Agent Framework (despliegue HA).

## Triaje rápido

1. ¿El servicio responde? `curl -s localhost:8080/healthz` (liveness) y
  `curl -s localhost:8080/readyz` (readiness). `/health` sigue como alias.
2. ¿Cuántas réplicas vivas? `kubectl -n ciel get pods -l app.kubernetes.io/name=ciel`.
   Si < `minAvailable` del PDB, el servicio está degradado pero no caído.
3. ¿El HPA está disparado? `kubectl -n ciel get hpa` — revisar `TARGETS`/`REPLICAS`.
4. Revisar logs: `kubectl -n ciel logs -l app.kubernetes.io/name=ciel --tail=200`.

## Síntomas y acciones

### 1. Healthcheck falla en una réplica (CrashLoopBackOff)
- `kubectl -n ciel describe pod <pod>` para ver `Events` y `Last State`.
- `kubectl -n ciel logs <pod> --previous` para el crash anterior.
- Si es error de arranque del gateway, aislar con `uv run ciel serve` local con los
  mismos env (`CIEL_TENANT`, `CIEL_PROVIDER_URL`, `CIEL_API_KEY` vía Secret, y en
  prod `CIEL_STATE_BACKEND=postgres` + `CIEL_STATE_DSN`).
- `/readyz` devuelve `not_ready` si el `StateBackend` no está conectado/migrado
  (p.ej. Postgres caído). La réplica no recibe tráfico hasta que `readyz` sea `ready`.

### 2. HIL (aprobación humana) bloqueada
- Un nodo de grafo con `require_approval` pausa el `GraphRunner` y persiste
  `paused=True`. Si nadie aprueba, el flujo queda detenido (no es un crash).
- Verificar rol del aprobadador: debe tener `approve:*` (rol `admin`).
  `uv run ciel rbac check --subject <user> --action approve:deploy`.
- Reanudar vía `GraphRunner.approve(run_id, approver=..., rbac=..., action=...)`
  desde el código/CLI correspondiente, o denegar con `deny`.

### 3. Resume multi-réplica tras caída (Fase 14 / F15+F16)
- El state de checkpoint/session vive en un **StateBackend compartido**
  (`PostgresStateBackend` en prod, `SqliteStateBackend` local en dev), NO en el
  PVC efímero de una réplica. Por eso N>=2 réplicas rehidratan el MISMO checkpoint
  tras caída de nodo: no dependen de RWX.
- Para reanudar un `run_id` en otra réplica usa `claim_run_lease` (lease
  idempotente por run_id con TTL). Si otra réplica ya tiene el lease vivo, la
  reanudación es rechazada (evita doble ejecución). Ver
  `src/ciel/runtime/resume.py`.
- Si una réplica murió sin liberar el lease, espera a que expire (`DEFAULT_LEASE_TTL_SECONDS=300`)
  o libera manualmente vía `release_run_lease(backend, run_id=...)`.
- Los dashboards de Studio (costo/trace) son **best-effort por réplica**; el state
  compartido es solo checkpoint/session/board/audit (ver `deploy.md`).

### 4. Spans/auditoría no aparecen
- `uv run ciel observe` confirma el exporter. Si se usó `--otel-endpoint`, verificar
  conectividad al collector (Tempo/Jaeger/OTel Collector).
- El audit inmutable (`HashChainAuditSink`) escribe **JSONL particionado por
  tenant/session** en el PVC de audit (NO es SQLite; ver `backup.md`).

### 5. Canal de mensajería caído (Teams/Discord/WebUI)
- Verificar health del router: `curl -s localhost:8080/v1/messaging/<channel>/health`.
- Revisar que el adapter correspondiente esté montado en `make_app` (`ciel serve`)
  y que las rutas de webhook apunten al endpoint correcto.
- Para pruebas offline usar `FakeAdapter` (`ciel chat --adapter fake`).

## Backup antes de rollback
- Antes de `helm rollback`, respalda audit/board/state (ver `backup.md` /
  `scripts/backup_state.py`).
