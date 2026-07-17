# Runbook: Backup y restore de audit/board/state

Este runbook describe el respaldo de los tres volúmenes de estado de Ciel. Es
**crítico distinguir los formatos**, porque el método de backup difiere:

| Componente            | Formato real            | Ruta (chart)                 | Método de backup                 |
|-----------------------|-------------------------|------------------------------|----------------------------------|
| **Audit** (`enterprise/audit.py`) | JSONL append-only particionado por `tenant/session` (`{base}/{tenant}/{session}/{tenant}-{session}.jsonl`) | `/var/lib/ciel/audit` | Copiar archivos JSONL (NO es SQLite) |
| **Board** (`orchestration/board.py`) | SQLite (WAL) cuando se pasa `path` | `/var/lib/ciel/board` (si se monta) | `sqlite3 .backup` / `.dump` |
| **Checkpoint/session** (Fase 14 / F15) | SQLite local (`StateBackend`) o Postgres compartido | `/var/lib/ciel/state` (SQLite) o `CIEL_STATE_DSN` (Postgres) | Copiar `.sqlite` o `pg_dump` |

> ⚠️ El audit **NO** es SQLite. El `HashChainAuditSink` escribe JSONL
> particionado (ver `src/ciel/enterprise/audit.py`). Los comandos `sqlite3`
> sobre el audit del runbook anterior eran **incorrectos** y se eliminan.

## Backup del audit (JSONL)

```bash
POD=$(kubectl -n ciel get pods -l app.kubernetes.io/name=ciel -o jsonpath='{.items[0].metadata.name}')

# Copiar TODO el árbol de auditoría particionado por tenant/session.
kubectl -n ciel cp "$POD:/var/lib/ciel/audit" /tmp/ciel-audit-$(date +%s)
```

El script `scripts/backup_state.py` automatiza esto (volca audit+board+state a
JSON/S3 opcional). Ver abajo.

## Backup del board (SQLite)

```bash
POD=$(kubectl -n ciel get pods -l app.kubernetes.io/name=ciel -o jsonpath='{.items[0].metadata.name}')

# Snapshot coherente de SQLite (WAL) vía .backup
kubectl -n ciel exec "$POD" -- sh -c \
  "sqlite3 /var/lib/ciel/board/board.db '.backup /tmp/board.bak'"
kubectl -n ciel cp "$POD:/tmp/board.bak" /tmp/ciel-board-$(date +%s).bak
```

## Backup del state (Fase 14 / F15)

* **SQLite** (default dev): copiar el archivo `.sqlite` directamente.
* **Postgres** (prod, `CIEL_STATE_BACKEND=postgres`): `pg_dump "$CIEL_STATE_DSN" > /tmp/ciel-state.sql`.

## Restore

```bash
# Detener el Deployment (escalar a 0) para evitar escrituras durante el restore.
kubectl -n ciel scale deploy/ciel --replicas=0

# Audit (JSONL): restaurar el árbol de archivos.
kubectl -n ciel cp /tmp/ciel-audit-<ts> "$POD:/var/lib/ciel/audit"

# Board (SQLite): restaurar el .bak.
kubectl -n ciel cp /tmp/ciel-board-<ts>.bak "$POD:/var/lib/ciel/board/board.db"

kubectl -n ciel scale deploy/ciel --replicas=2
```

## Verificar integridad del audit (hash chain)

La cadena de hashes SHA-256 del JSONL se verifica con `verify()`:

```bash
uv run python -c "
from ciel.enterprise.audit import HashChainAuditSink
sink = HashChainAuditSink(base_path='/tmp/ciel-audit-<ts>')
import asyncio
print('verify:', asyncio.run(sink.verify(tenant_id='acme', session_id='<sid>')))
"
```

`verify()` devuelve `True` si la cadena no fue alterada; `False` si algún
registro fue manipulado. El audit es append-only: no hacer `DELETE` sobre los
JSONL en producción.

## Script automatizado (scripts/backup_state.py)

```bash
# Local: vuelca audit+board+state a un directorio JSON local.
uv run python scripts/backup_state.py --audit-dir /var/lib/ciel/audit \
    --board-db /var/lib/ciel/board/board.db --state-db /var/lib/ciel/state/state.sqlite \
    --out /tmp/ciel-backup

# Con S3 (opcional): define CIEL_BACKUP_S3=s3://bucket/prefix
CIEL_BACKUP_S3=s3://mi-bucket/ciel uv run python scripts/backup_state.py ...
```

## Retención

- Programar backup periódico (CronJob `BackupJob` en el chart Helm, ver
  `deploy/helm/ciel/templates/backupjob.yaml`) fuera de la ventana de pico.
- El audit es append-only; el board/state son reemplazables desde el backup.
