# Changelog

Todas las versions siguen [SemVer](https://semver.org/lang/es/). v1.0.0 está
reservada para la madurez/GA del framework; las fases pendientes son `0.x`.

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
