# Changelog

Todas las versions siguen [SemVer](https://semver.org/lang/es/). v1.0.0 está
reservada para la madurez/GA del framework; las fases pendientes son `0.x`.

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
