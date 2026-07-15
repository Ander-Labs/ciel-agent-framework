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
- `MemoryStore`: memoria declarativa (SQLite + FTS5).
- `CheckpointStore` + `CheckpointedAgentRuntime`: punto de reanudación durable.

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
