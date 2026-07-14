# Deploy

Ciel está diseñado para correr en VPS o Kubernetes. Incluye Dockerfile, Compose
y un chart Helm HA.

## Local / VPS con Docker Compose

El repo trae `docker-compose.yml` (gateway de control + volumen de auditoría).
Construye y levanta:

```bash
docker compose up --build
```

El gateway queda en `http://localhost:8000` con auth por `CIEL_API_KEY`.

## Imagen / Dockerfile

`Dockerfile` usa `uv` multi-stage con extras `[gateway,acp]` y entrypoint
`ciel serve`. Build local:

```bash
docker build -t ciel:local .
docker run -e CIEL_API_KEY=tu-key -p 8000:8000 ciel:local ciel serve
```

## Kubernetes con Helm (HA)

Chart en `deploy/helm/ciel` con alta disponibilidad:

- `replicaCount: 2`
- `PodDisruptionBudget` (`minAvailable: 1`)
- `HorizontalPodAutoscaler` (2–10 réplicas, target CPU 70%)
- `podAntiAffinity` + `topologySpreadConstraints` (maxSkew 1)

```bash
helm install ciel deploy/helm/ciel -n ciel --create-namespace
```

## Levantar el gateway (ciel serve)

```bash
ciel serve --host 0.0.0.0 --port 8000 --tenant acme --otel
```

Variables de entorno relevantes (ver [Configuración](configuration.md)):

- `CIEL_API_KEY` — auth del gateway.
- `CIEL_PROVIDER_URL` — endpoint del LLM (si no se setea, arranca con un
  provider *echo* offline).
- `CIEL_API_KEY` / `CIEL_MODEL` — credenciales y modelo por defecto.
- `CIEL_TENANT` — tenant por defecto.
- `CIEL_TEAMS_WEBHOOK` / `CIEL_DISCORD_WEBHOOK` — adapters de canal.
- `CIEL_BOARD_DB` — ruta de la DB del board Kanban.
- `--otel-endpoint` — colector OTLP (si no, traces in-memory offline-safe).

## Human-in-the-Loop en producción

Los nodos de grafo marcados `require_approval=True` pausan y persisten
`paused=True`. Reanudas con `GraphRunner.approve()`/`deny()` (requiere rol con
RBAC `approve:*`). Esto permite aprobar acciones peligrosas antes de ejecutarlas.
