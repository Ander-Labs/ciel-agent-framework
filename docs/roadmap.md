# Roadmap público — Ciel Agent Framework

> Documentación oficial de `mana-ciel` (import `ciel`). Este roadmap describe las
> capacidades que llegarán a los usuarios y las versiones previstas. Es
> orientativo: el orden y las fechas pueden ajustarse según aprendizajes de uso.
> Para el diario técnico de ingeniería, consulta los canales internos del equipo.

## Visión

Un framework enterprise para construir agentes autónomos y sistemas multi-agente,
model-agnostic y deploy-agnostic, con multitenancy y trazabilidad nativas
(k8s/VPS). Principio rector: *harness-first*, ejecutable sobre planificación
extendida, y — a largo plazo — agentes que **crean, verifican, refinan y enseñan
sus propios skills** (autonomía auto-incremental) llevada a nivel enterprise.

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
- **Streaming** de respuestas (`astream`) y **loop ReAct multi-turno** integrados.
- `@ciel.tool` con inferencia de schema, validación Pydantic V2 y errores DX claros.
- Objetivo: un agente funcional con tres líneas, offline-safe.

### v0.6 — 📋 Escala y HA real

- Backend de estado/checkpoint **compartido** (Postgres o SQLite sobre PVC)
  para supervivencia multi-réplica sin pérdida de sesión.
- Ejecución de N réplicas con health + reanudación de checkpoint compartido.
- Runbooks operativos completos (despliegue, incidente, rollback, backup, HPA).

### v0.7 — 📋 Ciel Studio (Web UI + observabilidad visual)

- **Web UI** y dashboard mínimo operativo: sesiones, board, loops y estado.
- Visualización de trazas y replay de session (time-travel); cost dashboard.

### v0.8 — 📋 Enterprise reforzado

- **SSO/OIDC** con proveedor real (no solo verificación local de JWT).
- **Vault** para secretos dinámicos y rotación.
- **Guardrails** + sandbox de ejecución de código del agente (Docker/gVisor).

### v0.9 — 📋 Providers y multimodal

- **LiteLLM** como meta-provider (100+ modelos), fallback y balanceo.
- Providers clave: Anthropic, Azure OpenAI, Gemini, Ollama (local), vLLM/TGI.
- **Multimodal** nativo (visión/audio/video).

### v1.0 — 📋 Memoria, RAG y conocimiento

- Memoria avanzada (episódica + semántica) y RAG listo para enterprise
  (plantillas, hybrid search, re-ranking, document loaders, caché semántico).

### v1.1 — 📋 Evaluación y testing

- `ciel evaluate` (DeepEval/RAGAS/TruLens), KPIs, MockModel, CI actions,
  red-teaming y regression testing.

### v1.2 — 📋 Autonomía I: Skill Library

- **Skill Library** versionada por tenant; el agente **crea y verifica** skills
  en sandbox y las **refina** con el uso. (Diferenciador de autonomía.)

### v1.3 — 📋 Autonomía II: auto-aprendizaje

- Self-reflection y learning-from-failure; **prompt evolution** versionado;
  introspección y estado cognitivo explicable.

### v1.4 — 📋 Autonomía III: curricula y exploración

- Autonomous goal setting + curriculum; knowledge graph y transfer learning
  entre dominios.

### v1.5 — 📋 Inteligencia colectiva

- Cross-agent knowledge transfer; composición y marketplace de skills;
  skill evolution tree y métricas de velocidad de aprendizaje.

### v1.6 — 📋 APIs multi-lenguaje y despliegue moderno

- API REST/gRPC para exponer agentes; SDKs (TS/Go/Java/Rust); IaC y GitOps.

### v1.7 — 📋 Observability GA y multi-cloud

- OTel a collector real con dashboards/alertas; integraciones (LangFuse, W&B,
  DataDog, PagerDuty); multi-cloud sin vendor lock-in.

### v1.8 — 📋 API stability y ecosistema

- API pública estable (semver + deprecación); ecosistema de plugins, galería de
  templates, docs bilingüe (es/en), benchmark público.

### v2.0 — 📋 GA (meta-agente)

- Meta-agentes que eligen estrategia y auto-optimizan su aprendizaje; límites de
  seguridad autónomos que evolucionan con la experiencia; compliance automático
  (SOC2/ISO/GDPR) y disaster recovery. API estable, SLA y despliegue multi-cloud.

---

## Cómo seguir el progreso

- Releases en PyPI: `pip install mana-ciel` / `uv add mana-ciel`.
- CHANGELOG y guías en este mismo sitio.
- Cada versión menor se acompaña de tag, wheels y notas de upgrade.
