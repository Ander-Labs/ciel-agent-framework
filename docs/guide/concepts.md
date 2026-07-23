# Conceptos centrales

Ciel organiza la ejecución de agentes en torno a unas pocas piezas. Este diagrama
muestra el flujo básico:

```
            ┌─────────────┐
 usuario --> │   Prompt   │
            └──────┬──────┘
                   │
            ┌──────▼──────┐
            │   Runtime   │  DefaultAgentRuntime
            │ (agent loop)│
            └──────┬──────┘
        ┌──────────┼───────────┐
        │          │           │
  ┌─────▼────┐ ┌──▼─────┐ ┌───▼──────┐
  │ Provider │ │ Tools  │ │  Graph/  │
  │ (LLM)    │ │(toolset)│ │  Flow    │
  └──────────┘ └────────┘ └──────────┘
        │          │
        └──────┬───┘
               │
         ┌─────▼─────┐
         │  Gateway  │  FastAPI + adapters (Teams/Discord/WebUI)
         └───────────┘
```

## Capa de alto nivel (recomendada)

Para el caso común usas cuatro piezas de la API pública (`import ciel`):

- **`ciel.Agent`** — entrada de alto nivel. Encapsula provider + registro de
  tools + dispatcher + runtime. Métodos `run()` (sync) y `arun()` (async).
- **`@ciel.tool`** — convierte una función Python en tool, infiriendo el
  esquema desde type hints + docstring. Ver [Tools](tools.md).
- **`ciel.Context`** — objeto de inyección de dependencias (tenant/session/user)
  disponible dentro de las tools que lo declaren.
- **`ciel.AgentResponse`** — resultado ergonómico: `.text`, `.tool_results`,
  `.tool_calls`, `.messages`, `.raw`.

```python
import ciel

@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

agent = ciel.Agent(provider=mi_provider, tools=[add])
resp = agent.run("Suma 2 + 3", tenant_id="acme")
print(resp.text)
```

Por debajo, esta capa se apoya en las primitivas siguientes, que puedes usar
directamente cuando necesites control fino.

## Runtime

`DefaultAgentRuntime` (en `ciel.runtime`) orquesta el ciclo:
envía el `ChatRequest` al provider, si el provider devuelve `tool_calls` los
ejecuta vía el dispatcher y vuelve a llamar al provider con los resultados, hasta
`finish_reason == "stop"`. Es durable cuando se combina con
`CheckpointedAgentRuntime`.

## Tool / Toolset

- `ToolSpec`: nombre, descripción, esquema de parámetros (JSON-schema-like).
- `Tool`: `ToolSpec` + `callable_`.
- `ToolRegistry` / `ToolsetSchema`: agrupan tools en *toolsets* (conjuntos
  activables por tenant o por agente).
- `DefaultToolDispatcher`: ejecuta `tool_calls` del provider contra el registry.

## Provider

Interfaz `ChatProvider` (ABC) con `complete`, `stream`, `models`. Ciel trae
`OpenAICompatibleProvider`, `AnthropicProvider` y `GeminiProvider` como builtins.
Puedes crear el tuyo subclassando `ChatProvider`. Ver [Providers](providers.md).

## Tenant (multitenancy)

Casi todas las operaciones aceptan `tenant_id`. Aísla memoria, checkpoints,
auditoría, cuotas de costo y rate-limit por inquilino. Es nativo, no un
añadido: pasas `tenant_id=` en el runtime y en los tools.

## Session / Memory / Checkpoint

- `Session`: conversación aislada (estado en runtime/orchestration).
- `EpisodicStore`: memoria episódica nativa por `(tenant_id, session_id)` (SQLite), inyectada en el agente vía `Agent(memory=...)`. Aislada por tenant, offline-safe.
- `CheckpointStore` + `CheckpointedAgentRuntime`: punto de reanudación durable.

## Auto-aprendizaje (Autonomía II, v0.13)

Tres primitivas aditivas y **offline-safe** (sin red ni API keys) que convierten
al agente en capaz de aprender de sus fallos y volverse explicable:

- **Self-reflection + learning-from-failure** (`ciel.runtime.reflection_agent_integration`):
  `Agent(reflection=True)` genera tras cada run una *lección* determinista cuando
  un tool falla (resumen estructurado de qué tool falló y por qué), y la persiste
  como memoria episódica `role="lesson"` (multitenant, reutiliza F17). El resumen
  está disponible en `AgentResponse.reflection`.
- **Prompt evolution versionado** (`ciel.runtime.prompt_versioning`):
  `PromptRegistry` / `PromptVersion` versionan las `instructions` con semver +
  `sha256` + linaje, persistido en SQLite/Postgres vía `StateBackend` (aislado
  por `tenant_id`). `registry.update(name, text, bump="minor")` crea una nueva
  versión trazable.
- **Introspección / estado cognitivo** (`ciel.runtime.cognitive_state`):
  `Agent(introspection=True)` registra un `CognitiveSnapshot` post-run (versión de
  prompt activa, turnos de memoria, tool calls, fallo, confianza heurística) en
  `cognitive_state_log` e inyecta un bloque `[Estado cognitivo]` en el system
  prompt. `agent.introspect()` vuelca los últimos snapshots.

Todas se enganchan sin reescribir `ciel.api`: patron `install_*_support` (igual
que memoria/skills). La CLI `ciel reflect` las opera desde línea de comandos.

## Graph / Flow

`ciel.orchestration.graph` define grafos de nodos con estado. Un nodo puede
marcarse `require_approval=True` para **Human-in-the-Loop**: el runner pausa y
persiste `paused=True` hasta que un rol autorizado (RBAC `approve:*`) aprueba o
rechaza. `flows`, `chat`, `swarm`, `supervisor` son orquestadores de
multi-agente sobre estas primitivas.

## Gateway

`ciel.gateway` expone el framework vía FastAPI (`ciel serve`), con routers para
adapters de canal (Teams, Discord, WebUI) y auth por `CIEL_API_KEY`. Ver
[Deploy](deploy.md).
