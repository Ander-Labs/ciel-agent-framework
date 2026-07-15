# Runbook: Rollback

Procedimiento de rollback de un release de Ciel usando Helm.

## Antes de rollback (respaldar estado)

1. Listar revisiones:
   ```bash
   helm -n ciel history ciel
   ```
2. Respaldar el audit/checkpoint (SQLite en PVC) antes de tocar nada:
   ```bash
   kubectl -n ciel cp <pod>:/var/lib/ciel/audit /tmp/ciel-audit-backup-$(date +%s)
   ```
   El audit es hash-chained e inmutable; un rollback de la app NO borra el PVC.
3. Anotar la revisión buena conocida (la última estable).

## Rollback a la revisión anterior

```bash
helm -n ciel rollback ciel <revision> --wait --timeout 300s
```

- El PDB garantiza que durante el rollback quede al menos `minAvailable: 1` réplica
  disponible (no hay down total si el cluster tiene nodos suficientes).
- Tras el rollback, verificar health:
  ```bash
  kubectl -n ciel get pods -l app.kubernetes.io/name=ciel
  curl -s localhost:8080/health
  ```

## Rollback de la imagen (sin cambiar chart)

Si solo la imagen está rota, fijar un tag conocido:
```bash
helm upgrade ciel deploy/helm/ciel --reuse-values \
  --set image.tag=0.2.0
```

## Rollback de la aplicación (código/CLI local)

Si el incidente es de la librería (no del chart), revertir en el repo y reconstruir
wheel/imagen:
```bash
git revert <bad-commit>
uv build
docker build -t ciel:<tag> .
helm upgrade ciel deploy/helm/ciel --reuse-values --set image.tag=<tag>
```

## Post-rollback
- Confirmar que el audit inmutable sigue verificándose (`HashChainAuditSink.verify`).
- Documentar la causa raíz en el incidente.
