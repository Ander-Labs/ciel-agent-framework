# `ciel.gateway` — Superficie de gateway

Bloques de construcción públicos del gateway:

* `create_control_app` — plano de control FastAPI para el runtime del agente.
* `gateway.mcp` — cliente MCP (stdio/HTTP) + host MCP + integración con el runtime.
* `WebhookAdapter` / `SlackAdapter` — adapters de mensajería entrante.
* `create_webhook_router`, `create_slack_webhook_router`,
  `create_teams_webhook_router`, `create_discord_webhook_router`,
  `create_webui_router` — montan adapters en una app FastAPI existente.
* `mount_mcp_app` — app FastAPI que expone el endpoint MCP host (`/mcp`).
* `make_app` — construye la aplicación FastAPI completa del gateway.

::: ciel.gateway
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.gateway.base
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.server
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.adapter
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.adapter_slack
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.messaging
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.mcp
    options:
      show_root_heading: false
      members: true

::: ciel.gateway.auth
    options:
      show_root_heading: false
      members: true
