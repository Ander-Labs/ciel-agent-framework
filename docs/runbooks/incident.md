# Runbook: Incidente

Procedimiento ante incidentes en producción de Ciel Agent Framework (despliegue HA).

## Triaje rápido

1. ¿El servicio responde? `curl -s localhost:8080/health` (o el Service expuesto).
2. ¿Cuántas réplicas vivas? `kubectl -n ciel get pods -l app.kubernetes.io/name=ciel`.
   Si < `minAvailable` del PDB, el servicio está degradado pero no caído.
3. ¿El HPA está disparado? `kubectl -n ciel get hpa` — revisar `TARGETS`/`REPLICAS`.
4. Revisar logs: `kubectl -n ciel logs -l app.kubernetes.io/name=ciel --tail=200`.

## Síntomas y acciones

### 1. Healthcheck falla en una réplica (CrashLoopBackOff)
- `kubectl -n ciel describe pod <pod>` para ver `Events` y `Last State`.
- `kubectl -n ciel logs <pod> --previous` para el crash anterior.
- Si es error de arranque del gateway, aislar con `uv run ciel serve` local con los
  mismos env (`CIEL_TENANT`, `CIEL_PROVIDER_URL`, `CIEL_API_KEY` vía Secret).

### 2. HIL (aprobación humana) bloqueada
- Un nodo de grafo con `require_approval` pausa el `GraphRunner` y persiste
  `paused=True`. Si nadie aprueba, el flujo queda detenido (no es un crash).
- Verificar rol del aprobadador: debe tener `approve:*` (rol `admin`).
  `uv run ciel rbac check --subject <user> --action approve:deploy`.
- Reanudar vía `GraphRunner.approve(run_id, approver=..., rbac=..., action=...)`
  desde el código/CLI correspondiente, o denegar con `deny`.

### 3. Checkpoint no reanuda tras caída de réplica
- Con `ReadWriteOnce` la réplica que pierde su nodo pierde su volumen efímero; la
  reanudación solo es posible en la réplica que conserva el PVC. Migrar a RWX o
  backend remoto (ver `docs/dev/FASE8_DESIGN.md`).

### 4. Spans/auditoría no aparecen
- `uv run ciel observe` confirma el exporter. Si se usó `--otel-endpoint`, verificar
  conectividad al collector (Tempo/Jaeger/OTel Collector).
- El audit inmutable (`HashChainAuditSink`) escribe JSONL en el PVC de audit.

### 5. Canal de mensajería caído (Teams/Discord/WebUI)
- Verificar health del router: `curl -s localhost:8080/v1/messaging/<channel>/health`.
- Revisar que el adapter correspondiente esté montado en `make_app` (`ciel serve`)
  y que las rutas de webhook apunten al endpoint correcto.
- Para pruebas offline usar `FakeAdapter` (`ciel chat --adapter fake`).

## Comunicación
- Abrir incidente con: alcance (tenants afectados), síntoma, réplicas afectadas,
  pasos ya intentados. No hacer `helm rollback` ciego sin respaldar primero
  (ver `rollback.md`).
