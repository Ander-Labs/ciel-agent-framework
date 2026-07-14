# Runbook: Despliegue HA (Helm)

Este runbook cubre el despliegue de Ciel Agent Framework en modo
High-Availability con el chart `deploy/helm/ciel` (versión 0.2.0).

## Prerrequisitos

- Cluster Kubernetes >= 1.25 con `metrics-server` instalado (requerido por el HPA).
- `kubectl` y `helm` >= 3.12 configurados contra el contexto destino.
- StorageClass con `ReadWriteMany` (RWX) si se comparte el volumen de audit/checkpoint
  entre réplicas. Si solo hay `ReadWriteOnce`, el chart monta un PVC por Deployment
  (ver nota de checkpoint compartido en `docs/dev/FASE8_DESIGN.md`).
- Secret con la API key del proveedor LLM (no plaintext en values):

  ```bash
  kubectl create secret generic ciel-llm \
    --from-literal=CIEL_API_KEY=sk-...
  ```

## Desplegar

```bash
cd A:/Apps/Agents/ciel-agent-framework
helm lint deploy/helm/ciel                     # validación estática
helm template ciel deploy/helm/ciel            # revisar manifiestos renderizados
helm upgrade --install ciel deploy/helm/ciel \
  --namespace ciel --create-namespace \
  --set gateway.defaultTenant=acme \
  --set gateway.providerApiKeySecret=ciel-llm \
  --set gateway.model=gpt-4o-mini
```

Por defecto el chart arranca **2 réplicas** con PDB (`minAvailable: 1`),
HPA (2–10 réplicas, target CPU 70%) y anti-affinity por `kubernetes.io/hostname`.

## Verificar salud

```bash
kubectl -n ciel get pods -l app.kubernetes.io/name=ciel
kubectl -n ciel get hpa, pdb
# Health en las tres superficies (control/MCP/webhook) responde 200:
kubectl -n ciel port-forward svc/ciel 8080:8080 &
curl -s localhost:8080/health
```

## Escalar número de réplicas base

```bash
helm upgrade ciel deploy/helm/ciel --reuse-values --set replicaCount=3
# o dejar que el HPA lo gestione (minReplicas/maxReplicas).
```

## Notas de checkpoint compartido (HA)

El `MemoryStore` escribe SQLite en disco. Para que N>=2 réplicas rehidraten el
mismo checkpoint tras la caída de 1, el directorio de audit/checkpoint debe ser
compartido (RWX) o usar un backend remoto. Con `ReadWriteOnce` cada réplica tiene
su propio SQLite: la reanudación tras caída de réplica funciona solo para la
réplica que conserva su volumen. Ver `docs/dev/FASE8_DESIGN.md` sección 1.
