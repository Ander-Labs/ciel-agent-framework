# Cookbook

Recetas cortas y copiables con la API de alto nivel de Ciel
(`@ciel.tool`, `ciel.Agent`, `ciel.Context`, `AgentResponse`).

- [Agente con múltiples tools](multi_tool.md)
- [Multitenancy con `Context`](context_tenant.md)
- [Tools asíncronas](async_tool.md)
- [Instrucciones de sistema](system_instructions.md)
- [Provider real (OpenAI-compatible)](real_provider.md)
- [Auto-provider y loop multi-turno (Fase 11)](auto_provider_multiturn.md)
- [Contenido multimodal (imágenes)](multimodal.md)
- [Auto-aprendizaje / introspección (Fase 19)](self-learning.md)

Todas las recetas offline usan un `DummyProvider` (subclase de
`ciel.providers.ChatProvider`) para ejecutarse sin red ni API keys.
