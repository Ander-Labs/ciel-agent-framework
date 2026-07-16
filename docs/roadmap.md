# Roadmap público — Ciel Agent Framework

> Documentación oficial de `mana-ciel` (import `ciel`). Este roadmap describe las
> capacidades que llegarán a los usuarios y las versiones previstas. Es
> orientativo: el orden y las fechas pueden ajustarse según aprendizajes de uso.
> Para el diario técnico de ingeniería, consulta los canales internos del equipo.

## Visión

Un framework enterprise para construir agentes autónomos y sistemas multi-agente,
model-agnostic y deploy-agnostic, con multitenancy y trazabilidad nativas
(k8s/VPS). Principio rector: *harness-first*, ejecutable sobre planificación
extendida.

## Leyenda de estado

- ✅ Disponible
- 🟡 En desarrollo
- 📋 Planificado

---

## Hitos por versión

### v0.4 — ✅ Disponible (actual)

Base sólida y usable en producción:

- **Orquestación best-of-breed**: grafos estilo LangGraph, flows estilo CrewAI,
  group-chat estilo AutoGen, root-agent estilo ADK, y session state persistente
  por tenant.
- **Agencia autónoma**: bucle durable con reintentos exponenciales y
  reanudación tras reinicio (`ciel loop run` / `ciel loop resume`).
- **Enterprise**: RBAC/OIDC, auditoría inmutable (hash-chain), governance de
  costos, secretos (Vault/K8s/env) y rate-limiting por tenant.
- **Deploy**: Helm (HA: PDB, HPA, anti-affinity), OTel/metrics, adapters
  (Teams/Discord/Web UI), Human-in-the-loop en grafos.
- **Developer Experience**: fachada ergonómica, `ciel init` offline-safe, guías
  y cookbooks, API reference pública.

### v0.5 — 📋 Developer Experience II

Bajar la curva de adopción para nuevos usuarios:

- Creación de agentes en una línea: `model="gpt-4o"` elige el provider
  automáticamente (auto-provider desde la cadena del modelo).
- **Streaming** de respuestas (`astream`) de primera clase.
- **Loop ReAct multi-turno** integrado en la fachada.
- Validación y errores multi-tenant más claros en la superficie pública.
- Objetivo: un agente funcional con tres líneas, offline-safe.

### v0.6 — 📋 Escala y HA real

- Backend de estado/checkpoint **compartido** (Postgres o SQLite sobre PVC)
  para supervivencia multi-réplica sin pérdida de sesión.
- Ejecución de N réplicas con health + reanudación de checkpoint compartido.
- Runbooks operativos completos (despliegue, incidente, rollback, backup, HPA).

### v0.7 — 📋 Interfaces y UI

- **Web UI** y dashboard mínimo operativo.
- Adapters (Teams/Discord/Web UI) con integración end-to-end y fakes offline.
- Experiencia de observación visual de sesiones, board y loops.

### v0.8 — 📋 Enterprise reforzado

- **SSO/OIDC** con proveedor real (no solo verificación local de JWT).
- **Vault** para secretos dinámicos y rotación.
- Auditoría y RBAC de grado enterprise con trazabilidad cruzada.

### v0.9 — 📋 Observabilidad GA

- **OTel** a collector real, dashboards y alertas listas para producción.
- Corrección de métricas de spans y trazas distribuidas entre réplicas.

### v1.0 — 📋 GA

- **API pública estable** con garantías de versionado semántico (semver) y
  política de deprecación documentada.
- Despliegue **multi-cloud** (Helm / Kustomize / Terraform) y marketplace de charts.
- Ecosistema: registro de plugins y galería de templates comunitarios.
- SLA y documentación de soporte enterprise.

---

## Cómo seguir el progreso

- Releases en PyPI: `pip install mana-ciel` / `uv add mana-ciel`.
- CHANGELOG y guías en este mismo sitio.
- Cada versión menor se acompaña de tag, wheels y notas de upgrade.
