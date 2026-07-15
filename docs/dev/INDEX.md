# Índice de desarrollo — Ciel Agent Framework

Última actualización: 2026-07-14. Estado verificado: **230 passed, 2 skipped**
(base Fases 0–8 + Fase 9). Fase 8 CERRADA: Helm HA, OTel centralizado, adapters
Teams/Discord/WebUI, HIL en grafo y release v0.2.0 entregados. Fase 9 CERRADA:
plugin system, GeminiProvider, tools de fábrica y `ciel init` offline.
release v0.1.0 (wheels + CHANGELOG), Dockerfile / Compose / Helm HA operativos,
Fase 5 CERRADA (módulos `graph`, `flows`, `chat`, `root` y `session`), Fase 6 CERRADA
(módulo `agent`: `EventLoop` durable + `AutonomousAgent`) y Fase 7 CERRADA
(paquete `enterprise`: `RBACEngine`+`OIDCVerifier`, `HashChainAuditSink` inmutable,
`CostGovernor`, `SecretStore` Vault/K8s/env, `TenantRateLimiter`; CLIs `ciel rbac` /
`ciel cost`, offline-safe).
Fases 0–4 CERRADAS.

## Estado por fase

| Fase | Tema | Estado | Verificación |
|------|------|--------|--------------|
| 0 | Fundación | ✅ Cerrada | CLI base + contratos + MT mínimo |
| 1 | Runtime básico | ✅ Cerrada | providers, tool-loop, memory, skills, checkpoints |
| 2 | Gobierno enterprise | ✅ Cerrada | approvals, redaction, audit, traces, sandbox |
| 3 | Multiagente durable | ✅ Cerrada | spec, supervisor, topology, queue, board, CLI |
| 4 | Superficies y despliegue | ✅ Cerrada | gateway, MCP, ACP, adapters, `ciel serve`, Docker/Helm |
| 5 | Best-of-breed | ✅ Cerrada (graph/flows/chat/root/session) | ver `docs/dev/FASE5_DESIGN.md` + `TASKS.md` |
| 6 | Agencia autónoma en bucle | ✅ Cerrada (`agent`: EventLoop + AutonomousAgent) | ver `docs/dev/FASE6_DESIGN.md` + `TASKS.md` |
| 7 | Enterprise duro | ✅ Cerrada (`enterprise`: rbac/oidc, audit inmutable, cost, secrets, ratelimit) | ver `docs/dev/FASE7_DESIGN.md` + `TASKS.md` |
| 8 | Deploy HA + observabilidad + madurez | ✅ Cerrada (Helm HA/OTel/adapters/HIL entregados + release v0.2.0) | ver `docs/dev/FASE8_DESIGN.md`, `FASE8_PROGRESS.md`, `docs/runbooks/` |
| 9 | Extensibilidad — plugin system, providers reales, tools de fábrica, DX | ✅ Cerrada (ciel.plugins/default_registry, entry points ciel.providers/tools/agents, GeminiProvider builtin, tools_builtins echo/datetime/http_get/file_read/shell, ciel init offline, bug raíz ToolProvider.execute corregido) | ver `docs/dev/FASE9_PROGRESS.md` |

## Documentos de progreso por fase

- `docs/dev/FASE0_PROGRESS.md` — Observabilidad, Security, Runtime, Tests (24→suite base)
- `docs/dev/FASE1_PROGRESS.md` — Runtime básico
- `docs/dev/FASE2_PROGRESS.md` — Gobierno enterprise
- `docs/dev/FASE3_PROGRESS.md` — Multiagente durable (spec/supervisor/board/queue)
- `docs/dev/FASE3_RESUME.md` — Reanudación / pendientes de Fase 3
- `docs/dev/FASE4_PROGRESS.md` — Superficies y despliegue (gateway/MCP/ACP/Helm)
- `docs/dev/FASE5_PROGRESS.md` — Orquestación best-of-breed (graph + flows + chat + root)
- `docs/dev/FASE5_DESIGN.md` — Diseño best-of-breed (Fase 5+)
- `docs/dev/FASE6_PROGRESS.md` — Agencia autónoma en bucle (EventLoop + AutonomousAgent)
- `docs/dev/FASE6_DESIGN.md` — Diseño Fase 6 (EventLoop durable + resume tras reinicio)
- `docs/dev/FASE7_PROGRESS.md` — Enterprise duro (RBAC/OIDC, audit inmutable, cost, secrets, ratelimit)
- `docs/dev/FASE7_DESIGN.md` — Diseño Fase 7 (contratos exactos de `ciel.enterprise`)
- `docs/dev/FASE8_DESIGN.md` — Diseño Fase 8 (checkpoint compartido HA, contrato adapters, diseño HIL)
- `docs/dev/FASE8_PROGRESS.md` — Deploy HA + observabilidad + madurez (entregado: Helm HA, OTel, adapters, HIL; release v0.2.0 CERRADA)
- `docs/dev/FASE9_PROGRESS.md` — Extensibilidad: plugin system (ciel.plugins/default_registry + entry points), GeminiProvider builtin, tools_builtins, ciel init offline, bug raíz ToolProvider.execute corregido
- `docs/runbooks/` — deploy / incident / rollback / backup (audit+board SQLite) / hpa
- `docs/dev/PENDIENTES.md` — Gap analysis Fases 7/8 (lo que falta por terminar)
- `docs/dev/CIERRE_SESION.md` — Cierre con subagentes: board SQLite, SSE, +5 tests (116)

## Documentos de diseño y gobierno

- `docs/Prompt.md` — Análisis best-of-breed (ADK/LangGraph/AutoGen/CrewAI/LlamaIndex)
- `docs/ROADMAP.md` — Roadmap fases 0–4 (checkboxes)
- `docs/CHARTER.md` — Carta del proyecto
- `docs/CI.md` — CI
- `docs/design/multi_tenancy.md` — Diseño de multitenancy
- `docs/sdk/README.md` — SDK público (make_app, ciel serve, etc.)

## Artefactos de release (verificados en disco)

- `Dockerfile` — multi-stage uv, extras `[gateway,acp]`, entrypoint `ciel serve`
- `docker-compose.yml` — control gateway + volumen de audit
- `deploy/helm/ciel/` — Chart.yaml, values.yaml, templates (PDB/HPA/Service/Pvc + probes)
- `deploy/example-enterprise/` — `ciel.yaml` + `config.py` + `serve.py`
- `docs/runbooks/` — deploy / incident / rollback / backup audit+board / hpa (Fase 8)
- `CHANGELOG.md` — v0.1.0 (Fase 4) + entradas Fase 5/6/7 (graph, flows/chat/root, agent, enterprise)
- `dist/` — wheels generados (`uv build`)

## Comandos de verificación

```bash
uv run pytest -q            # esperado: 230 passed, 2 skipped (base F0-8 + Fase 9: test_fase9_plugins 8 + test_fase9_tools 5)
uv build                   # genera wheels en dist/
uv run ciel serve          # arranca app compuesta (control + MCP + webhook)
uv run ciel swarm run      # orquestación desde AgentSpec YAML
uv run ciel board list     # tablero kanban (persistencia SQLite vía CIEL_BOARD_DB)
uv run ciel graph demo     # grafo de estado demo offline (Fase 5)
uv run ciel flow run       # flow event-driven demo offline (Fase 5)
uv run ciel chat group     # group chat de 3 agentes que converge offline (Fase 5)
uv run ciel root route     # root agent routing offline (Fase 5, session state opcional)
uv run ciel loop run        # agente autónomo en bucle offline (Fase 6)
uv run ciel loop resume     # reanuda loop tras reinicio (Fase 6, requiere --db)
uv run ciel rbac list-roles # roles y permisos RBAC (Fase 7, offline)
uv run ciel rbac check      # verifica permiso de un subject (Fase 7)
uv run ciel cost status     # gasto/presupuesto por tenant (Fase 7, offline)
uv run ciel observe         # verifica exporter OTel (Fase 8, offline-safe)
uv run ciel serve --otel otlp://collector:4317   # tracing OTLP (Fase 8)
uv run ciel serve           # monta routers Teams/Discord/WebUI en /v1/messaging/{channel}/health
uv run ciel chat --adapter fake   # demo canal con FakeAdapter (Fase 8, offline)
```

## Notas

- Repo SIN git inicializado: el estado se mantiene consistente en disco; no hay
  commits. Si se inicializa git, el primer commit debe incluir todo el árbol.
- `generate_tasks.py` regenera un borrador de `TASKS.md` (hasta Fase 4); la
  versión canónica es `TASKS.md` en la raíz (incluye Fase 5+).
- Multi-tenancy estricto: endpoints `/v1/agent/run` y `/v1/tools/...` exigen
  `tenant_id` (400 si falta).
