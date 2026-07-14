# Ejemplo enterprise de Ciel Agent Framework

Despliegue de referencia del gateway compuesto (control + MCP host + webhook)
con **multi-tenancy estricto** y un manifesto de configuración central.

## Estructura

```
example-enterprise/
├── ciel.yaml        # config central: provider + tenant por defecto + approval policy
├── config.py        # loader ligero de ciel.yaml (yaml + env)
├── serve.py         # arranca la app compuesta con uvicorn leyendo ciel.yaml
└── README.md
```

## Uso

```bash
cd deploy/example-enterprise

# 1) exporta la API key (nunca en plaintext dentro de ciel.yaml)
export CIEL_API_KEY=sk-...

# 2) instala los extras de gateway/ACP
uv pip install -e "../../[gateway,acp]"

# 3) arranca el gateway
python serve.py
#   o bien con el CLI estándar:
#   ciel serve --tenant acme --host 0.0.0.0 --port 8080
```

## Superficies expuestas

| Superficie | Método + ruta | Notas |
|---|---|---|
| Control | `GET /health`, `GET /info` | health/version/proveedores |
| Control | `POST /v1/agent/run` | **requiere `tenant_id`** (400 si falta) |
| Control | `POST /v1/tools/{toolset}/{name}` | **requiere `tenant_id`** |
| Control | `GET /v1/board/list` | kanban (filtrable por tenant) |
| MCP host | `POST /mcp/` | JSON-RPC: `initialize`, `tools/list`, `tools/call` |
| MCP host | `GET /mcp/health` | health del host MCP |
| Webhook | `POST /v1/messaging/webhook` | ingesta inbound (WebhookAdapter) |
| Webhook | `GET /v1/messaging/webhook/health` | health del router |

## Multi-tenancy

El gateway nunca relaja el aislamiento: `/v1/agent/run` y `/v1/tools/...`
devuelven `400` si no reciben `tenant_id` y no hay tenant por defecto
configurado. En este ejemplo `ciel.yaml` fija `default_tenant: acme`, pero
cualquier request puede sobreescribirlo con su propio `tenant_id`.

## Proveedor

Sin `CIEL_PROVIDER_URL` el gateway arranca con un *echo provider* offline
(útil para smoke tests). Con `ciel.yaml` apuntando a un endpoint
OpenAI-compatible, el runtime usa el LLM real. Las API keys se resuelven desde
variables de entorno referenciadas en `ciel.yaml` (`api_key_env`), listas para
inyección desde un Secret en Kubernetes.
