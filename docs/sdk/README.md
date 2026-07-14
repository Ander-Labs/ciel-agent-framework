# Ciel SDK

Guía rápida de uso del SDK de `ciel` para construir agentes empresariales, orquestaciones multi-agente y adaptadores de despliegue.

> Nota: este documento apunta a `v0.1.0`.

## Requisitos

- Python >= 3.14
- `uv` como gestor de ejecución
- Instalar en modo editable: `uv pip install -e ".[dev,gateway]"`

## Quickstart mínimo

```python
import asyncio
from ciel.providers import ProviderConfig, ProviderRegistry
from ciel.runtime import (
    StaticToolProvider,
    DefaultToolDispatcher,
    DefaultAgentRuntime,
    ChatRequest,
    ChatMessage,
    ToolSpec,
)
from ciel.observability import InMemoryAuditSink


async def main() -> None:
    provider = ProviderRegistry()
    provider.register(
        "local",
        ProviderFactory.from_config(
            ProviderConfig(
                name="local",
                base_url="http://localhost:8000/v1",
                api_key="replace-me",
                default_model="local-model",
            )
        ),
    )

    def echo(context, text: str) -> dict:
        return {"text": text}

    tools = {
        "default": [
            ToolSpec(
                name="echo",
                description="Echo irreducible para demo.",
                parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            )
        ]
    }
    tool_provider = StaticToolProvider(tools)
    dispatcher = DefaultToolDispatcher(provider=tool_provider)
    runtime = DefaultAgentRuntime(
        provider=provider.get("local"),
        dispatcher=dispatcher,
        audit_sink=InMemoryAuditSink(),
    )

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Decí hola con la herramienta echo.")],
        tools=[tool_provider.registry._tools["default"]["echo"].spec],
        model="local-model",
    )
    result = await runtime.run_agent_loop(request=request, tenant_id="tenant-1")
    print(result.response.choice.message.content)


if __name__ == "__main__":
    asyncio.run(main())
```

## Ejemplo enterprise mínimo reproducible

Objetivo: un flujo ejecutable sin dependencias externas vivas que cubra runtime, herramientas, auditoría y orquestación durable.

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ciel.providers import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ChatMessage,
    ChatChoice,
    ModelInfo,
    ProviderRegistry,
)
from ciel.runtime import (
    StaticToolProvider,
    DefaultToolDispatcher,
    DefaultAgentRuntime,
    ToolSpec,
)
from ciel.observability import InMemoryAuditSink
from ciel.orchestration.spec import AgentSpec, AgentStep
from ciel.orchestration.supervisor import Supervisor
from ciel.orchestration.topology import TopologyEngine


@dataclass
class EchoProvider(ChatProvider):
    provider_name = "echo"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        text = " ".join(message.content for message in request.messages if message.content)
        return ChatResponse(
            choice=ChatChoice(
                message=ChatMessage(role="assistant", content=f"ECHO:{text}")
            )
        )

    async def stream(self, request: ChatRequest):
        yield await self.complete(request)

    async def models(self) -> list[ModelInfo]:
        return [ModelInfo(id="echo-model", provider=self.provider_name)]


async def main() -> None:
    provider = EchoProvider()
    registry = ProviderRegistry()
    registry.register("echo", provider)

    tool_provider = StaticToolProvider(
        {
            "default": [
                ToolSpec(
                    name="echo",
                    description="Repite el texto recibido.",
                    parameters={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                )
            ]
        }
    )
    dispatcher = DefaultToolDispatcher(provider=tool_provider)
    runtime = DefaultAgentRuntime(
        provider=provider,
        dispatcher=dispatcher,
        registry=registry,
        audit_sink=InMemoryAuditSink(),
    )

    spec = AgentSpec(
        id="enterprise-demo",
        name="Enterprise Demo",
        topology="pipeline",
        steps=[
            AgentStep(id="step-1", name="Echo step", run="echo"),
            AgentStep(id="step-2", name="Echo step 2", run="echo", depends_on=["step-1"]),
        ],
    )

    async def runner(step: AgentStep) -> str:
        request = ChatRequest(
            messages=[ChatMessage(role="user", content=f"Run {step.id}")],
            toolset="default",
        )
        result = await runtime.run_agent_loop(request=request, tenant_id="tenant-1")
        return result.response.choice.message.content

    supervisor = Supervisor(budget=3)
    engine = TopologyEngine(agent_spec=spec, runner=runner, budget=supervisor.budget)
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
```

## Runtime y herramientas

- `DefaultAgentRuntime` ejecuta un loop de tool calls con approval policies.
- `ToolRegistry` y `ToolsetSchema` exponen contratos versionados por tenant/toolset.
- `ChatRequest` / `ChatResponse` son DTOs de entrada/salida de proveedores.

## Deployment: gateway y adaptadores

### App compuesta (recomendada)

`ciel.gateway.server.make_app` compone en una sola FastAPI app el control
gateway, el host MCP y el router de webhook. Se arranca vía el comando CLI
`ciel serve` (uvicorn) o importándola directamente para tests:

```python
from ciel.gateway.server import make_app

# tenant por defecto; el control gateway sigue exigiendo tenant_id por request.
app = make_app(tenant_id="acme")
# superficies:
#   control : GET  /health , /info ; POST /v1/agent/run , /v1/tools/{toolset}/{name}
#   mcp     : POST /mcp/ , GET /mcp/health   (JSON-RPC)
#   webhook : POST /v1/messaging/webhook , GET /v1/messaging/webhook/health
```

```bash
# Arranque del gateway (multi-superficie) con uvicorn:
uv pip install -e ".[gateway,acp]"
ciel serve --host 0.0.0.0 --port 8080 --tenant acme

# O con variables de entorno:
CIEL_TENANT=acme CIEL_PROVIDER_URL=https://api.openai.com/v1 \
  CIEL_API_KEY=sk-... CIEL_MODEL=gpt-4o-mini ciel serve
```

### Control gateway por separado

```python
from ciel.gateway.base import create_control_app
from ciel.runtime import DefaultAgentRuntime, DefaultToolDispatcher, ToolProvider

# (cablear provider + dispatcher como en el quickstart)
app = create_control_app(runtime=runtime, tenant_id="acme")
```

### Host MCP por separado

```python
from ciel.gateway import mount_mcp_app

# dispatcher = runtime.dispatcher  (DefaultToolDispatcher)
mcp_app = mount_mcp_app(dispatcher=dispatcher, tenant_id="acme", path="/mcp")
# expone POST /mcp (JSON-RPC: initialize, tools/list, tools/call) + GET /health
```

### Adapter FastAPI (webhook inbound)

```python
from ciel.gateway import create_webhook_router
from ciel.gateway.adapter import WebhookAdapter

app.include_router(create_webhook_router(WebhookAdapter()))
```

### Opciones de despliegue

| Variante | Comando | Uso recomendado |
|---|---|---|
| CLI local | `uv run ciel run` | desarrollo y debugging |
| In-process | importar `DefaultAgentRuntime` | tests y microservicios |
| Gateway compuesto | `ciel serve` (uvicorn) | deploy k8s/VPS, MCP + control + webhook |
| ACP server | `ciel.acp` (`create_app`) | editores con agente ACP |

## Referencia rápida

- Proveedores: `ciel.providers`
- Runtime: `ciel.runtime`
- Orquestación: `ciel.orchestration`
- Gateway: `ciel.gateway`
- CLI: `ciel.cli.main:app`
