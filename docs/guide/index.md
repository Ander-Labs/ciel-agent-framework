# Ciel Agent Framework — Guía para desarrolladores

Ciel es un **framework Python enterprise** (>=3.11) para construir agentes y
sistemas multi-agente **model-agnostic** y **deploy-agnostic**, con
multitenancy nativo, trazabilidad, MCP/ACP y adapters de canal funcionales.

Esta guía es para **desarrolladores que quieren USAR el framework**. El diario de
ingeniería vive en `docs/dev/` y no es necesario leerlo para empezar.

## Por qué Ciel

- **Extensible por diseño**: providers, tools y agents se registran vía plugins
  (entry points) sin tocar el core.
- **Offline-safe**: todo corre sin red ni API keys (providers mock, OTel
  in-memory, sandboxeado). Ideal para tests y CI.
- **Enterprise desde el día 1**: RBAC, auditoría inmutable (hash-chained),
  gobernanza de costos, rate-limiting por tenant, secretos por backend.
- **Deploy real**: Docker, Compose y Helm HA (PDB + HPA) listos.

## Instalación

```bash
pip install mana-ciel
# o con uv:
uv pip install mana-ciel
```

El paquete PyPI se llama `mana-ciel` (el nombre `ciel` estaba tomado en PyPI),
pero el import y el CLI se mantienen:

```python
import ciel
```

```bash
ciel --help
```

## Empezar ya

- [Quickstart](quickstart.md): tu primer agente en <5 min, sin red.
- [Conceptos](concepts.md): Agent, Runtime, Tool, Provider, Tenant, Graph, Gateway.
- [Providers](providers.md): usar OpenAI/Anthropic o registrar el tuyo.
- [Tools](tools.md): definir y ejecutar herramientas.
- [Plugins](plugins.md): extender sin tocar el core (preview v0.3.0).
- [Deploy](deploy.md): Docker, Compose, Helm HA, `ciel serve`.
- [Configuración](configuration.md): `ciel.yaml`, env vars, tenants.

## Estado

- PyPI: `mana-ciel` (v0.2.0 publicada; Fase 9 en curso).
- Repo: https://github.com/Ander-Labs/ciel-agent-framework
