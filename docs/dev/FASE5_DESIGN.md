# Ciel — Diseño Fase 5+ (best-of-breed)

Fecha: 2026-07-10. Estado base verificado: **116 passed, 1 skipped**, release
v0.1.0 (wheels + CHANGELOG), Dockerfile / Compose / Helm operativos. Fases 0–4
CERRADAS. Este documento es el diseño de madurez que lleva a ciel por encima
del promedio del mercado combinando lo mejor de ADK, LangGraph, AutoGen,
CrewAI y LlamaIndex sobre el núcleo Hermes.

## 0. Tesis

ciel NO debe copiar un solo framework. Su ventaja es heredar de Hermes Agent:
tools genéricos, **skills como memoria procedimental**, memory cross-session,
delegación de subagentes y MCP nativo. Los otros frameworks construyen eso
encima; ciel lo tiene. La Fase 5+ compone lo mejor de cada uno y lo enchufa
como módulos sobre ese núcleo.

Diferenciador de mercado defendible: **agentes evolutivos (skills que
aprenden) + multitenancy nativo + orquestación best-of-breed**. Ninguno de los
5 frameworks tiene esa combinación junta.

## 1. Lo mejor de cada framework (features a robar)

### ADK (Google) — más nuevo
- Agentes especializados + `sub_agents`: un root agent coordina y enruta a
  specialists. Jerarquía nativa, no monolito.
- **Code execution tool**: ejecuta código en sandbox y devuelve resultado.
- Session state persistente entre turnos.
- Built-in tools (Search, RAG, code exec) + CLI excelente.
- Deploy a Vertex AI / Gemini Enterprise; evaluación/telemetry integrado.

### LangGraph — madurez en control de flujo
- Grafo EXPLÍCITO de estado (state machine cíclica/condicional). Control
  preciso, no "magia".
- Persistence + checkpointing: reanudación y time-travel. Lo mejor del mercado.
- Human-in-the-loop: interrupt antes de nodos, approve/reject.
- Platform: background runs, crontabs, deployment.

### AutoGen (Microsoft) — conversación
- Agentes CONVERSABLES entre sí (`GroupChat` + `GroupChatManager`). Varios
  agentes resuelven en diálogo.
- Separación limpia Agent / Model / Tool / GroupChat.
- Code execution dockerizado; HIL conversable.

### CrewAI — UX enterprise y flows
- Role-playing agents (role/goal/backstory).
- Crews + **Flows event-driven** (`start`/`listen`/`router`, state, resume de
  long-running).
- Process sequential/hierarchical/hybrid + guardrails + memory + knowledge +
  observability baked in.
- Enterprise: triggers (Gmail, Slack, Salesforce, Teams), RBAC, team mgmt.

### LlamaIndex — datos/RAG
- Data framework completo: ingestion, indexing, retrieval.
- `AgentWorkflow` / Workflows event-driven por steps.
- Function-calling y ReAct agents; LlamaTrace observability.

## 2. Qué aporta Hermes (núcleo ya presente en ciel)

- Sistema de TOOLS/integraciones genérico (terminal, file, web, browser, mcp).
- **SKILLS** como memoria procedimental reutilizable (diferenciador).
- DELEGACIÓN de subagentes (orquestación real).
- MEMORY cross-session persistente.
- MCP support nativo.
- CLI-first.

## 3. Qué pide el sector enterprise (no negociable)

- Multitenancy AISLADO (scope/DB por tenant — requisito k8s/VPS del proyecto).
- Auth + RBAC real (OIDC/SAML SSO, no solo API key).
- Auditoría/compliance (trazas inmutables, SOC2-ready).
- Secret management (Vault / K8s secrets, nunca hardcode).
- Rate limiting + cuotas por tenant/usuario.
- Observabilidad end-to-end (metrics + traces + logs centralizados).
- Human-in-the-loop configurable.
- Cost governance por modelo/tenant.
- Deployment HA (k8s, healthchecks, rollback).

## 4. Matriz feature ganadora → estado en ciel (verificado en árbol)

| Feature                         | ciel hoy              | origen sugerido        |
|---------------------------------|-----------------------|------------------------|
| Agnóstico modelo (providers)    | ✓ presente            | (ya lo tienes)         |
| Skills procedimentales          | ✓ runtime/skills.py   | HERMES (diferenciador) |
| Memory + checkpoints            | ✓ runtime/*           | HERMES + LangGraph     |
| Subagentes / delegación         | ✓ orchestration/*     | HERMES + ADK.sub_agents|
| Gateway+Slack+MCP               | ✓ gateway/*           | (ya lo tienes)         |
| Seguridad approvals/redaction   | ✓ security/*          | enterprise             |
| Observability otel/metrics      | ✓ observability/*     | enterprise             |
| Board/Supervisor/Queue/Budget   | ✓ orchestration/*     | (ya lo tienes)         |
| Grafo de estado explícito       | ✗ FALTA              | LangGraph              |
| Code execution sandbox          | ~ sandbox/* (parcial) | ADK                    |
| Group chat multi-agente         | ✗ FALTA              | AutoGen                |
| Flows event-driven + resume     | ✗ FALTA              | CrewAI                 |
| RAG / Knowledge base            | ✗ FALTA              | LlamaIndex             |
| Session state por tenant        | ~ parcial (board)     | ADK                    |
| RBAC / OIDC SSO                 | ✗ FALTA              | enterprise             |
| Audit inmutable                 | ~ JSONL (mutable)     | enterprise             |
| Deploy k8s/Helm                 | ✓ Helm (no HA)        | enterprise             |

## 5. Diseño "best-of-breed" para ciel (sin acoplarse a ninguno)

La jugada no es copiar uno, es componer lo mejor y que el núcleo Hermes
(skills + memory + delegación) sea el pegamento:

- a) **ORQUESTACIÓN** = ADK.sub_agents + LangGraph
  - Root agent coordina y enruta a specialist agents (ADK).
  - Cada flujo crítico se modela como grafo de estado con checkpoint
    (LangGraph) para reanudación/time-travel.
- b) **RUNTIME EVOLUTIVO** = HERMES (skills+memory) + CrewAI.Flows
  - Skills = memoria procedimental que el agente REFINA sola (lo "evolutivo").
  - Flows event-driven con resume para jobs long-running (CrewAI).
- c) **CONVERSACIÓN** = AutoGen.GroupChat
  - Para problemas que necesitan debate entre agentes (revisión de código, planes).
- d) **DATOS** = LlamaIndex
  - RAG/Knowledge conectado como TOOL más, no acoplado al core.
- e) **ENTORNO** = gateway ya hecho
  - Slack/MCP listos; añadir Teams/Discord/Web UI como adapters (patrón CrewAI triggers).
- f) **ENTERPRISE** = capa transversal
  - Multitenancy scope en board+session; RBAC en gateway.auth; audit inmutable
    en observability; secret en security.

## 6. Roadmap de ejecución (MVP → producción)

Ver `TASKS.md` Fase 5+ para el desglose con checkboxes. Resumen:

- **Fase 5 — Orquestación best-of-breed**: grafo de estado + checkpoint +
  flows event-driven + group chat + root_agent routing. Módulos:
  `ciel.orchestration.graph`, `.flows`, `.chat`, `.root`.
- **Fase 6 — Runtime evolutivo + datos**: skills que aprenden, code execution
  sandbox, RAG/knowledge como tool. Módulos: `ciel.runtime.skills` (tune),
  `.codex`, `.rag`, `.knowledge`.
- **Fase 7 — Enterprise duro**: RBAC/OIDC SSO, audit inmutable, cost governance,
  secret management (Vault/K8s), rate-limit por tenant. Módulos:
  `ciel.gateway.auth`, `ciel.observability.audit` (append-only), `.metrics`
  (cost), `ciel.security.secrets`.
- **Fase 8 — Deploy HA + madurez**: Helm HA (HPA/PDB/rollback), observabilidad
  OTel centralizada, adapters Teams/Discord/Web UI, HIL configurable, release
  v0.2.0.

## 7. Veredicto honesto

Tienes ~40% del esqueleto best-of-breed YA en disco (providers, skills, memory,
checkpoints, gateway, orchestration, security, observability, Helm). Los otros 5
frameworks construyen SU core encima de lo que tú ya heredas de Hermes.

Lo que falta para ser "el mejor": grafo de estado + code execution + group chat
+ flows + RAG + la capa enterprise dura (RBAC/audit/deploy HA). Ninguno es
imposible porque tu arquitectura ya está preparada para recibirlos como módulos.
