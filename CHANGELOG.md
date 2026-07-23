# Changelog

Todas las versions siguen [SemVer](https://semver.org/lang/es/). v1.0.0 está
reservada para la madurez/GA del framework; las fases pendientes son `0.x`.

## [0.13.0] — Fase 19: Autonomía II (auto-aprendizaje)

### Nuevo
- **Self-reflection + learning-from-failure** (`ciel.runtime.reflection_agent_integration`):
  `Agent(reflection=True)` genera tras cada run una lección determinista (offline,
  sin red) cuando un tool falla, y la persiste como memoria episódica
  `role="lesson"` (multitenant, reutiliza F17). Disponible en la property
  aditiva `AgentResponse.reflection`.
- **Prompt evolution versionado** (`ciel.runtime.prompt_versioning`):
  `PromptRegistry` / `PromptVersion` versionan las `instructions` con semver +
  `sha256` + linaje (`evolution_tree`), persistido en SQLite/Postgres vía
  `StateBackend` (aislado por `tenant_id`).
- **Introspección / estado cognitivo** (`ciel.runtime.cognitive_state`):
  `Agent(introspection=True)` registra un `CognitiveSnapshot` post-run en
  `cognitive_state_log` e inyecta un bloque `[Estado cognitivo]` en el system
  prompt; expone `Agent.introspect()`.
- **`ciel reflect`** (CLI Typer, `ciel.cli.reflect`): `run` (KPIs de
  auto-reflexión con `MockProvider`), `history` (evolution_tree de un prompt) e
  `introspect` (estado cognitivo de una sesión). Cableado en `ciel.cli.main`.
- **CI**: nuevo job `reflect` (offline, `MockProvider`, sin red).

### Cambios internos
- `StateBackend` (SQLite + Postgres): tablas `prompt_versions` y
  `cognitive_state_log` y sus métodos (`prompt_save`/`prompt_get`/
  `prompt_get_history`, `state_log_append`/`state_log_get_recent`), con filtro
  estricto por `tenant_id`.
- API pública **aditiva**: no se rompen `Agent`, `AgentResponse`, `ToolResult`
  ni `ChatProvider`; solo se añaden kwargs (`reflection=`, `introspection=`) y
  módulos `install_*_support`.

## [0.12.0] — Fase 18: Evaluación y testing

### Nuevo
- **`MockProvider` determinista** (`ciel.providers.MockProvider`): proveedor
  offline-safe (sin red ni API keys) con modos `fixed`/`echo`/`map`; registrado
  en `auto_provider` con prefijo `mock/`. Para tests y eval reproducibles.
- **`ciel evaluate`** (CLI Typer, `ciel.cli.evaluate`): `run` (KPIs en tabla
  Rich + exit-code por umbral), `regression` (gate contra `results.json`
  baseline) y `redteam` (prompt injection / fuga de tenant con assertions de
  aislamiento). Cableado en `ciel.cli.main`.
- **`ciel.eval`**: `Evaluator` (corre dataset sobre un agente/callable, acumula
  KPIs, exporta `results.json`), `EvalCase`, `load_dataset` (YAML) y métricas
  deterministas propias: `exact_match`, `contains`, `f1_token`, `faithfulness`,
  `context_relevance` (usa `Retriever` de `ciel.rag` si se pasa),
  `answer_relevance`.
- **Integración opt-in** con DeepEval/RAGAS/TruLens vía extra `eval`
  (`use_third_party=True`); degrada a métricas propias si el extra no está
  instalado (las funciones de terceros devuelven `None`).
- **Extra `eval`** en `pyproject.toml` (`deepeval`, `ragas`, `trulens-eval`);
  el core no lo requiere.
- **CI**: nuevo job `eval` en `.github/workflows/ci.yml` (offline, `MockProvider`,
  sin red) que corre `tests/eval` + smoke CLI y hace gate de regression.

### Cambios internos
- Corrección de documentación obsoleta: `docs/guide/concepts.md` refería
  `MemoryStore` (memoria declarativa FTS5) — ahora documenta `EpisodicStore`
  (memoria episódica nativa por `(tenant_id, session_id)`, Fase 17).
- API pública aditiva: `ciel.eval` (`Evaluator`, `EvalCase`, métricas,
  `load_dataset`) y `ciel.providers.MockProvider`. No rompe `Agent`,
  `AgentResponse`, `ToolResult` ni `ChatProvider`.

## [0.11.0] — Fase 17: Memoria, RAG y conocimiento

### Nuevo
- **Memoria episódica nativa (Pilar A, offline-safe)**: `ciel.runtime.memory_episodic`
  con `EpisodicStore` y `MemoryConfig`. Persiste user/assistant por
  `(tenant_id, session_id)`, con `append` / `get_recent` / `get_by_id` /
  `search` (filtrada **estrictamente por tenant** — sin fuga cross-tenant) /
  `clear_session`. Se recupera e inyecta como contexto en el system prompt del
  agente de forma aditiva (`Agent(memory=store)`).
- **RAG enterprise (Pilares B/C, offline-safe por defecto)**: nuevo paquete
  `ciel.rag` con `KnowledgeBase` / `Retriever` / `SemanticCache`, índice
  vectorial `InMemoryVectorStore` + `DeterministicEmbeddingProvider` (sin red),
  búsqueda híbrida BM25 + vector con fusión RRF y rerank, chunking configurable
  (token/paragraph), loaders MD/HTML/TXT (PDF opt-in) y tools RAG
  (`retrieve`, `kb_add`) que se enchufan al agente vía `rag_tools(kb)`.
- **API pública aditiva**: `ciel.EpisodicStore`, `ciel.MemoryConfig` y
  `install_agent_memory_support(Agent)` (mismo patrón que skills). Degrada
  graceful a "sin memoria" si no se configura. No rompe la API pública.
- **Aislamiento multi-tenant nativo** en toda memoria/RAG (requisito k8s/VPS).
- **Extra `rag` opcional** en `pyproject.toml` (`chromadb`, `pypdf`); el
  default corre sin red ni keys.

### Cambios internos
- `state_backend` gana métodos de memoria episódica (`memory_append`,
  `memory_get`, `memory_get_recent`, `memory_search_tenant`,
  `memory_clear_session`) sobre SQLite/Postgres, aislados por `tenant_id`.
- `Agent.arun`/`astream` usan `session_id` estable por agente para que la
  memoria episódica persista a lo largo de la conversación (antes se renovaba
  por run, rompiendo la persistencia).
- `memory_search_tenant` (SQLite) migrado de FTS5 trigram a `LIKE` por tenant
  (determinista, offline-safe y sin fuga cross-tenant).
- Tests offline de F17: 17 nuevos (memoria episódica, RAG end-to-end, tools,
  integración con `Agent`). Suite total: 434 passed / 7 skipped.

## [0.10.0] — Fase 16: Providers y multimodal

### Nuevo
- **Multimodal nativo (offline-safe)**: `ChatMessage.content` ahora acepta
  `str | list[dict]` (partes de contenido tipo `text`/`image_url`/`input_audio`).
  Helper `ChatMessage.text()` degrada multimodal a texto concatenado para
  consumo en CLI/gateway/ACP sin romper la API pública.
- **Serializers por proveedor**: OpenAI (`_normalize_content_parts`), Anthropic
  (`_anthropic_content` mapea data-URLs a bloques `image`), y Gemini
  (`_gemini_parts` → `inline_data`).
- **LiteLLM meta-provider (extra `litellm`)**: `LiteLLMProvider` expone 100+
  modelos vía un único contrato `ChatProvider`, con soporte de `Router` para
  fallback/balanceo y streaming. Offline-safe: import diferido; sin el extra,
  construcción lanza `ProviderError` claro. Registro condicional en
  `default_registry()` y rama en `ProviderFactory.from_config`.
- **Nuevos providers**: `AzureOpenAIProvider` (deployment + `api-version`),
  Ollama local y vLLM/TGI como `OpenAICompatibleProvider` con base_url por
  defecto. `auto_provider` reconoce prefijos `azure/`, `ollama/`, `vllm/`.
- Extra opcional `litellm` en `pyproject.toml`.

### Cambios internos
- Unificación de DTOs de chat: `runtime/__init__.py` re-exporta desde
  `runtime/tools.py` (única fuente con `ChatMessage.text()`), eliminando
  definiciones duplicadas.
- Ingress/consumo de mensajes (api, gateway, ACP, adapters, CLI) migrados a
  `content` multimodal + `.text()`.

### Tests
- +27 tests offline (F16-C multimodal, F16-A LiteLLM mock, F16-B Azure/Ollama/
  vLLM). Suite completa: **417 passed / 7 skipped**.

## [0.9.0] — Fase 15: Enterprise reforzado
OIDC/JWKS, Vault dinámico, sandbox + guardrails. (Ver historial de tags.)

## [0.8.0] — Fase 14: Escala y HA real
(Ver historial de tags.)
