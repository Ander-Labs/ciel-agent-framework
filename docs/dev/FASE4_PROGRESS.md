# Fase 4 — Progreso

Estado actual: COMPLETADA y verificada. Suite verde: 109 passed, 1 skipped.
Verificación: `uv run pytest -q` pasa; `uv build` genera wheels; `ciel serve`
arranca y expone las tres superficies; `swarm run` y `board` funcionan E2E.

## Entregables cerrados / verificados

- `pyproject.toml`: bug bloqueante corregido (lista `dependencies` mal
  anidada bajo `[project.urls]`). `mcp>=1.2` añadido a optional-deps
  `gateway`. `uv build` funciona (wheels generados en `dist/`).
- `ciel.gateway.base`: control HTTP API (`create_control_app`) con
  `/health`, `/info`, `/v1/agent/run`, `/v1/tools/{toolset}/{name}`,
  `/v1/board/list`. Multi-tenancy estricto: `/v1/agent/run` y
  `/v1/tools/...` exigen `tenant_id` (400 si falta).
- `ciel.gateway.mcp`: paquete MCP (cliente stdio/HTTP + server host
  JSON-RPC + integración runtime). Bugs previos corregidos.
- `ciel.gateway.adapter`: `WebhookAdapter` integrado vía
  `create_webhook_router()`. Hay además `SlackAdapter` +
  `create_slack_webhook_router()` (router independiente).
- `ciel.gateway.__init__`: corregido bug de 422 — los endpoints que usan
  `request: Request` fallaban con validación 422 porque `Request` se
  importaba DENTRO de la función bajo `from __future__ import annotations`
  (la anotación quedaba como string y FastAPI lo trataba como query param).
  Ahora `Request`/`APIRouter`/`FastAPI` se importan a nivel de módulo.
  Esto reparó 3 tests de Fase 4 que estaban rotos: el webhook router,
  `mount_mcp_app` y `test_serve_mcp_endpoint_lists_tools`.
- `ciel.gateway.server.make_app()`: app FastAPI compuesta (control + MCP
  host en `/mcp` + webhook en `/v1/messaging/webhook`) sobre un solo
  puerto, runtime offline (echo provider) por defecto, provider remoto vía
  `CIEL_PROVIDER_URL`. Expone también `/metrics` si hay prometheus-client.
- `ciel serve`: comando Typer que arranca uvicorn (`--host`, `--port`,
  `--tenant`), leyendo `CIEL_TENANT` por defecto. Verificación E2E:
  `/health` 200, `/v1/agent/run` con echo, `/mcp/health` 200, y el
  default tenant se aplica cuando el request no lo trae.
- `ciel.acp`: servidor ACP compatible IDEs (`create_app`), estable.
- Empaquetado: `Dockerfile` multi-stage (uv, extras `[gateway,acp]`,
  entrypoint `ciel serve`), `docker-compose.yml`, Helm chart
  (`deploy/helm/ciel`) con probes `/health`, Service, ConfigMap de tenant y
  PVC de audit.
- Docs SDK (`docs/sdk/README.md`) y ejemplo enterprise
  (`deploy/example-enterprise` con `ciel.yaml` + `serve.py`).
- Release v0.1.0: `uv build` (tar.gz + wheel) y `CHANGELOG.md`.

## Notas de verificación (estado real, sesión de auditoría)

- Conteo real de tests: **109 passed, 1 skipped** (no 85 ni 82+3 como
  figuraba en versiones previas de este doc / INDEX / ROADMAP).
- `ciel swarm run` funciona E2E con un `AgentSpec` YAML válido
  (`{id, kind, tool|prompt, depends_on}`); la clave `agent` NO existe en
  `AgentStep` (la firma real es id/kind/tool/prompt/depends_on/metadata).
- `ciel board add/list/show/assign` existen y funcionan, pero `KanbanBoard`
  se instancia en memoria por comando, así que NO hay persistencia entre
  invocaciones de CLI distintas. Es un pendiente conocido de Fase 3
  (ver FASE3_RESUME): persistir el board en SQLite.
- `ciel serve` smoke test vía `TestClient` confirma multi-tenancy por
  defecto y los 200 esperados.

## Criterio de cierre de Fase 4 — CUMPLIDO

Deploy enterprise en k8s/VPS con tracing, MCP, ACP y un adapter funcional;
imagen Docker oficial, Compose y Helm operativos; SDK y ejemplo documentados;
release v0.1.0 publicado; suite verde (109 passed / 1 skipped).
