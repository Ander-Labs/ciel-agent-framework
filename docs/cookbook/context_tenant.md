# Multitenancy con `Context`

Una tool puede recibir el contexto de ejecución declarando un parámetro anotado
con `ciel.Context`. Ciel lo inyecta en runtime y lo excluye del esquema JSON (el
modelo nunca lo ve). El `tenant_id` que pasas a `agent.run(..., tenant_id=...)`
llega intacto a la tool — así se preserva el aislamiento multi-tenant.

```python
import ciel
from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatChoice, ChatMessage, ChatResponse


@ciel.tool
def datos_cliente(customer_id: str, ctx: ciel.Context) -> dict:
    "Devuelve datos del cliente, aislados por tenant."
    # ctx.tenant_id permite consultar el almacén correcto del inquilino.
    return {"tenant": ctx.tenant_id, "customer_id": customer_id}


class DummyProvider(ChatProvider):
    provider_name = "dummy"

    async def complete(self, request):
        tc = [{"id": "c1", "name": "datos_cliente",
               "arguments": {"customer_id": "C-42"}}]
        msg = ChatMessage(role="assistant", content="", tool_calls=tc)
        return ChatResponse(
            choice=ChatChoice(message=msg, finish_reason="tool_calls"),
            metadata={"tool_calls": tc},
        )

    async def stream(self, request):
        return [await self.complete(request)]

    async def models(self):
        return (ModelInfo(id="dummy", provider="dummy"),)


agent = ciel.Agent(provider=DummyProvider(), tools=[datos_cliente], toolset="demo")
resp = agent.run("Trae el cliente", tenant_id="acme")

print(resp.tool_results[0].output)
```

Qué esperar:

```
{'tenant': 'acme', 'customer_id': 'C-42'}
```

El esquema JSON de `datos_cliente` **solo** contiene `customer_id`; el parámetro
`ctx` queda fuera del esquema que ve el modelo.
