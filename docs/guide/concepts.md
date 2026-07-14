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

## Agent

Un agente es la unidad que resuelve una tarea. En Ciel no necesitas una clase
`Agent` rígida: ensamblas un `Runtime` con un `Provider` (el LLM) y un
`Dispatcher` (las tools). El loop conversacional vive en
`DefaultAgentRuntime.run_agent_loop()`.

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
