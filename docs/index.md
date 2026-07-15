# Ciel — Framework enterprise de agentes autónomos :fontawesome-solid-robot:{ .no-select }

!!! example "Tagline"
    **Ciel** es un framework de agentes **enterprise** para Python (>=3.11):
    **multi-tenant**, **model-agnostic** y **deploy-agnostic**. Construye
    agentes autónomos y sistemas multi-agente con trazabilidad nativa,
    adapters de canal funcionales y una API de alto nivel de pocas líneas.

Distribuido en PyPI como `mana-ciel` (el import y el CLI se mantienen como
`ciel`):

```bash
pip install mana-ciel
ciel --help
```

---

## :material-rocket-launch: Tu primer agente en ~15 líneas

```python
import ciel

@ciel.tool
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

# Provider offline de ejemplo (sustitúyelo por OpenAI/Anthropic/Gemini)
from ciel.providers import OpenAICompatibleProvider
provider = OpenAICompatibleProvider(base_url="https://api.openai.com/v1",
                                   api_key="sk-...", default_model="gpt-4o")

agent = ciel.Agent(provider=provider, tools=[add], model="gpt-4o")
resp = agent.run("¿Cuánto es 2 + 3?", tenant_id="acme")
print(resp.text)
```

¿Sin API key a mano? El [Inicio rápido](guide/quickstart.md) incluye un
`DummyProvider` **100% offline** que puedes ejecutar ya mismo.

---

## :material-grid: Características principales

<div class="grid cards" markdown>

- :fontawesome-solid-building-columns: **Multi-tenancy nativo**
  ---

  Aislamiento, trazabilidad y cuotas por inquilino. El `tenant_id` fluye
  desde `Agent.run()` hasta cada tool vía `Context`.
  [:octicons-arrow-right-24: Multi-tenancy](design/multi_tenancy.md)

- :material-api: **API de alto nivel**
  ---

  `@ciel.tool`, `ciel.Agent`, `ciel.Context` y `AgentResponse`. Inferencia
  de esquema JSON desde type hints + docstring (Pydantic v2).
  [:octicons-arrow-right-24: Inicio rápido](guide/quickstart.md)

- :material-brain: **Model-agnostic**
  ---

  Providers incluidos para OpenAI-compatible, Anthropic y Gemini. Crea el
  tuyo subclassando `ChatProvider`.
  [:octicons-arrow-right-24: Providers](guide/providers.md)

- :material-tools: **Tools con inyección de dependencias**
  ---

  Declara un parámetro `Context` y Ciel lo inyecta y lo excluye del esquema.
  Tools síncronas o `async`.
  [:octicons-arrow-right-24: Tools](guide/tools.md)

- :material-shield-check: **Seguridad y HITL**
  ---

  Políticas de aprobación, redacción de secretos/PII y pausas
  Human-in-the-Loop sobre grafos de estado.
  [:octicons-arrow-right-24: Security](api-reference/security.md)

- :material-chart-arc: **Observabilidad**
  ---

  Auditoría multi-tenant y trazas de tool execution listas para exportar.
  [:octicons-arrow-right-24: Observability](api-reference/observability.md)

</div>

---

## :material-book-open-page-variant: Documentación

<div class="grid cards" markdown>

- :material-flag-checkered: **Guía**
  ---

  Empieza por el [Inicio rápido](guide/quickstart.md) y los
  [Conceptos](guide/concepts.md) centrales.
  [:octicons-arrow-right-24: Ir a la Guía](guide/quickstart.md)

- :material-sitemap: **Arquitectura**
  ---

  Diseño de [multi-tenancy](design/multi_tenancy.md), runtime, dispatcher y
  gateway.
  [:octicons-arrow-right-24: Ver arquitectura](design/multi_tenancy.md)

- :material-lifebuoy: **Runbooks (ops)**
  ---

  [Despliegue](runbooks/deploy.md), [incidentes](runbooks/incident.md),
  [rollback](runbooks/rollback.md), [backup](runbooks/backup.md) y
  [HPA](runbooks/hpa.md).
  [:octicons-arrow-right-24: Ver runbooks](runbooks/deploy.md)

- :material-code-braces: **Referencia de API**
  ---

  Módulos públicos generados con mkdocstrings:
  [CLI](api-reference/cli.md), [runtime](api-reference/runtime.md),
  [providers](api-reference/providers.md),
  [gateway](api-reference/gateway.md), [security](api-reference/security.md).
  [:octicons-arrow-right-24: Índice de la API](api-reference/index.md)

</div>

---

## :material-package-variant-closed: Estado del proyecto

| | |
|---|---|
| **PyPI** | `mana-ciel` (import `ciel`) |
| **Compatibilidad** | Python >= 3.11 |
| **Repositorio** | <https://github.com/Ander-Labs/ciel-agent-framework> |
| **Releases** | <https://github.com/Ander-Labs/ciel-agent-framework/releases> |
| **Licencia** | Consulta el repositorio |

¿Vienes de una versión anterior? Revisa la
[guía de upgrade](upgrade.md).
