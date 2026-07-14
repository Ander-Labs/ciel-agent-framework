# Configuración

Ciel se configura con un manifiesto `ciel.yaml`, variables de entorno y el
aislamiento por tenant. Las API keys **nunca** se ponen en plaintext: se
referencian por variable de entorno.

## ciel.yaml

Ejemplo (ver `deploy/example-enterprise/ciel.yaml`):

```yaml
default_tenant: "acme"
approval_policy: "manual"   # manual | smart | yolo

providers:
  - name: "openai"
    base_url: "https://api.openai.com/v1"
    api_key_env: "CIEL_API_KEY"     # se resuelve desde el entorno / SecretStore
    default_model: "gpt-4o-mini"
    tenant: "acme"
```

- `default_tenant`: inquilino por defecto para las llamadas sin tenant explícito.
- `approval_policy`: política de Human-in-the-Loop global (`manual` exige
  aprobación humana en nodos `require_approval`).
- `providers`: lista de providers con su `base_url`, variable de api key y modelo.

## Variables de entorno

| Variable               | Uso                                                  |
|------------------------|------------------------------------------------------|
| `CIEL_API_KEY`         | Auth del gateway y/o api key del LLM                 |
| `CIEL_PROVIDER_URL`    | Endpoint del LLM para `ciel serve` (si falta: echo offline) |
| `CIEL_MODEL`           | Modelo por defecto                                   |
| `CIEL_TENANT`          | Tenant por defecto                                   |
| `CIEL_TEAMS_WEBHOOK`   | Webhook de Teams para el adapter                     |
| `CIEL_DISCORD_WEBHOOK` | Webhook de Discord para el adapter                   |
| `CIEL_BOARD_DB`        | Ruta de la DB del board Kanban                       |

## Tenants

El multitenancy es nativo. Para activarlo:

1. Define `default_tenant` en `ciel.yaml` o pasa `tenant_id=` en cada llamada al
   runtime / tools.
2. La memoria, los checkpoints, la auditoría, el costo y el rate-limit se aíslan
   por `tenant_id` automáticamente.
3. El `CostGovernor` corta por presupuesto por tenant; el `TenantRateLimiter`
   aplica cuotas por tenant/usuario; el `RBACEngine` autoriza acciones por rol.

## Secretos

En producción resuelve keys con `ciel.enterprise.secrets.SecretStore`, que prueba
backends por prioridad: entorno → Kubernetes Secrets → Vault (si está
disponible). Nunca hardcodees credenciales en `ciel.yaml`.
