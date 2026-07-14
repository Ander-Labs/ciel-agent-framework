# Runbook: Escalado HPA

Ciel escala horizontalmente con el `HorizontalPodAutoscaler` definido en
`deploy/helm/ciel/templates/hpa.yaml`.

## Cómo funciona

- `minReplicas: 2`, `maxReplicas: 10`, `targetCPUUtilizationPercentage: 70`.
- Requiere `metrics-server` en el cluster (`kubectl get apiservice v1beta1.metrics.k8s.io`).
- La métrica de **requests/segundo** requiere un adaptador de métricas custom
  (p. ej. Prometheus Adapter) que exponga `ciel_requests_per_second`; el HPA
  actual escala por CPU. Documentar la instalación del adaptador fuera de este chart.

## Inspeccionar estado

```bash
kubectl -n ciel get hpa
kubectl -n ciel describe hpa ciel
```

## Forzar/ajustar escalado

```bash
# Cambiar límites base
helm upgrade ciel deploy/helm/ciel --reuse-values \
  --set ha.hpa.minReplicas=3 --set ha.hpa.maxReplicas=15

# O escalar manualmente (el HPA lo reajustará según métricas)
kubectl -n ciel scale deploy/ciel --replicas=4
```

## Anti-affinity y topología

- `podAntiAffinity` (preferred) esparce réplicas por `kubernetes.io/hostname`.
- `topologySpreadConstraints` (`maxSkew: 1`, `whenUnsatisfiable: ScheduleAnyway`)
  distribuye de forma uniforme.
- Si el cluster tiene pocos nodos, el scheduler puede dejar réplicas en el mismo
  nodo (preferred, no required) — añadir nodos o cambiar a `requiredDuringScheduling`
  si se requiere estricto.

## Verificar supervivencia a caída de 1 réplica

1. Identificar una réplica: `POD=$(kubectl -n ciel get pods -o name | head -1)`.
2. Simular caída: `kubectl -n ciel delete $POD` (el Deployment/HPA la repone).
3. Comprobar health y que el checkpoint compartido (si aplica) reanuda:
   `curl -s localhost:8080/health` y revisar logs de rehidratación.
