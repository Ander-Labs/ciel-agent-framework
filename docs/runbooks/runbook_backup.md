# Runbook: Backup y restore de audit/board (SQLite)

El audit inmutable (`HashChainAuditSink`) y el tablero kanban (`KanbanBoard`)
persisten en SQLite sobre el `MemoryStore`. En el chart HA viven en el PVC
`/var/lib/ciel/audit` (mountPath configurable en `values.yaml`).

## Backup

```bash
# Localizar el pod con el volumen montado
POD=$(kubectl -n ciel get pods -l app.kubernetes.io/name=ciel -o jsonpath='{.items[0].metadata.name}')

# Hacer snapshot coherente: detener escrituras o usar .backup de SQLite.
# Opción A: copia en caliente (SQLite tolera lectura concurrente, pero para
# consistencia usar .dump o vacuum into).
kubectl -n ciel exec "$POD" -- sh -c \
  "sqlite3 /var/lib/ciel/audit/audit.db '.backup /tmp/audit.bak'"

# Opción B: volcar a SQL (portable)
kubectl -n ciel exec "$POD" -- sh -c \
  "sqlite3 /var/lib/ciel/audit/audit.db '.dump' > /tmp/audit.sql"

kubectl -n ciel cp "$POD:/tmp/audit.bak" /tmp/ciel-audit-$(date +%s).bak
```

> Nota: si no hay `sqlite3` en la imagen, copiar el archivo `.db` directamente con
> `kubectl cp` y validarlo con `uv run python -c "import sqlite3; ..."`.

## Restore

```bash
# Detener el Deployment (escalar a 0) para evitar escrituras durante el restore
kubectl -n ciel scale deploy/ciel --replicas=0
kubectl -n ciel cp /tmp/ciel-audit-<ts>.bak "$POD:/var/lib/ciel/audit/audit.db"
kubectl -n ciel scale deploy/ciel --replicas=2
```

## Verificar integridad del audit (hash chain)

```bash
uv run python -c "
from ciel.enterprise.audit import HashChainAuditSink
sink = HashChainAuditSink(db_path='/tmp/ciel-audit-<ts>.bak')
print('verify:', sink.verify())
"
```
`verify()` devuelve `True` si la cadena no fue alterada; `False` si alguna línea
fue manipulada.

## Retención
- Programar backup periódico (CronJob) fuera de la ventana de pico.
- El audit es append-only; no hacer `DELETE` sobre el JSONL/SQLite en producción.
