# Ciel Agent Framework

**Framework Python enterprise** (>=3.11) para construir agentes y sistemas
multi-agente **model-agnostic** y **deploy-agnostic**, con multitenancy nativo,
trazabilidad, MCP/ACP y adapters de canal funcionales.

Distribuido en PyPI como `mana-ciel` (el import y el CLI se mantienen como
`ciel`):

```bash
pip install mana-ciel
ciel --help
```

## Empieza aquí

- [Guía rápida](guide/quickstart.md): tu primer agente en <5 min, 100% offline.
- [Conceptos](guide/concepts.md): Agent, Runtime, Tool, Provider, Tenant, Graph, Gateway.
- [Providers](guide/providers.md): usa OpenAI/Anthropic o registra el tuyo.
- [Plugins](guide/plugins.md): extiende sin tocar el core (entry points).
- [Tutorial de plugin](guide/tutorial_plugin.md): escribe tu primer plugin end-to-end.

## Arquitectura y operaciones

- [Multi-tenancy](design/multi_tenancy.md): aislación y trazabilidad por tenant.
- [Runbooks (ops)](runbooks/deploy.md): despliegue, incidentes, rollback, backup, HPA.
- [Roadmap](roadmap.md): estado de las fases del proyecto.
- [Upgrade v0.2.0 → v0.3.0](upgrade.md): guía de migración.

## Referencia

- [Referencia de API](api-reference/index.md): `ciel.cli`, `observability`, `adapters`,
  `gateway`, `providers`, `runtime`, `security`, `orchestration`.
- [SDK](sdk/README.md): cómo integrar Ciel como SDK.

## Estado

- PyPI: `mana-ciel` (v0.3.0 — Fase 9: extensibilidad).
- Repositorio: https://github.com/Ander-Labs/ciel-agent-framework
- Releases: https://github.com/Ander-Labs/ciel-agent-framework/releases
