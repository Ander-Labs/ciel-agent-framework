# Roadmap — Ciel Agent Framework

> Resumen de las fases del proyecto orientado a **usuarios** del framework.
> Para el diario técnico de ingeniería consulta `docs/dev/` (contenido interno,
> no publicado).

Ciel Agent Framework (`mana-ciel` en PyPI, paquete `ciel`, CLI `ciel`) es un
framework *enterprise* para construir agentes autónomos y sistemas multi-agente,
model-agnostic y deploy-agnostic, con multitenancy y trazabilidad nativas
(k8s/VPS).

## Estado de las fases

| Fase | Tema | Estado |
|------|------|--------|
| 0 | Fundación (SDK, CI, contratos base, CLI mínima) | ✅ Cerrada |
| 1 | Runtime básico (providers, tool-loop, memoria, skills, checkpoints) | ✅ Cerrada |
| 2 | Gobierno enterprise (approvals, redaction, audit, traces, sandbox) | ✅ Cerrada |
| 3 | Multiagente durable (spec, supervisor, topology, queue, board, CLI) | ✅ Cerrada |
| 4 | Superficies y despliegue (gateway, MCP, ACP, adapters, `ciel serve`, Docker/Helm) | ✅ Cerrada |
| 5 | Orquestación best-of-breed (graph/flows/chat/root/session) | ✅ Cerrada |
| 6 | Agencia autónoma en bucle (EventLoop + AutonomousAgent) | ✅ Cerrada |
| 7 | Enterprise duro (RBAC/OIDC, audit inmutable, cost governance) | ✅ Cerrada |
| 8 | Deploy HA + observabilidad + madurez de producción | ✅ Cerrada |
| 9 | Extensibilidad — plugin system, providers reales, tools de fábrica, DX | ✅ Cerrada |

## Fase 8 — Deploy HA + observabilidad + madurez de producción (✅ Cerrada)

Entregado y verificado:

- **Helm HA**: `replicaCount: 2`, PodDisruptionBudget (`minAvailable: 1`),
  HorizontalPodAutoscaler (2–10 réplicas, target CPU 70%), `podAntiAffinity` y
  `topologySpreadConstraints` en `deploy/helm/ciel`.
- **OpenTelemetry centralizado**: `init_tracing` (OTLP o in-memory), `span_count`,
  comando `ciel observe` y flag `--otel` en `ciel serve`.
- **Adapters de canal**: Teams / Discord / Web UI + `FakeAdapter` (`ciel.adapters`),
  con routers montados en `ciel serve`.
- **Human-in-the-loop en grafo**: `GraphNode.require_approval`,
  `GraphRunner.approve`/`deny` con chequeo RBAC (`approve:*`).
- **Runbooks operativos**: deploy / incident / rollback / backup de audit+board /
  HPA en `docs/runbooks/`.
- **Tests formales Fase 8** verdes.
- **Regresión completa verde**: 216 passed, 1 skipped (194 base F0–7 + 22 Fase 8).
- **Release v0.2.0**: tag + wheels + CHANGELOG.

## Fase 9 — Extensibilidad (✅ Cerrada — publicada en PyPI como `mana-ciel==0.3.0`)

Entregado y verificado:

- **Plugin system** (`ciel.plugins`): `default_registry` + auto-descubrimiento vía
  entry points (`ciel.providers`, `ciel.tools`, `ciel.agents`). Terceros pueden
  hacer `pip install mi-plugin-ciel` y su provider/tool aparece en el registry.
- **`GeminiProvider`** añadido a `ciel.providers` como builtin.
- **Tools de fábrica** (`ciel.runtime.tools_builtins`): `echo`, `datetime`,
  `http_get`, `file_read`, `shell`.
- **`ciel init`**: scaffold de proyecto offline e idempotente.
- **Bug raíz corregido**: `ToolProvider.execute` usa la firma oficial de callable.
- **Docs DX externas** `docs/guide/` + `mkdocs.yml`.
- **Regresión completa verde**: 230 passed, 2 skipped (base 216 + 14 Fase 9).
- **Release v0.3.0 publicado en PyPI**: `pip install mana-ciel==0.3.0`.

## Enlaces

- Releases de GitHub: <https://github.com/Ander-Labs/ciel-agent-framework/releases>
- Guía de migración v0.2.0 → v0.3.0: [upgrade.md](upgrade.md)
- Guía de uso (DX): `docs/guide/`
- Runbooks operativos: `docs/runbooks/`
