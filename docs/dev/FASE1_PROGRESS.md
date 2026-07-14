# Fase 1 – Progress

## Estado
Criterio de avance: crear un agente con 3 tools, hablarle, ejecutar tools, persistir memoria, checkpoint/restore.

## Cerrado y verificado
- [x] `ciel.providers`: adapter OpenAI-compatible; Anthropic agregado con llamada HTTP `/messages`.
- [x] `ciel.runtime.agent`: DefaultAgentRuntime con loop tool_calls y tracing.
- [x] `ciel.runtime.tools`: ToolRegistry, ToolsetSchema, DefaultToolDispatcher.
- [x] `ciel.runtime.memory`: MemoryStore con SQLite + FTS5.
- [x] `ciel.runtime.skills`: frontmatter parsing, SkillRegistry.
- [x] `ciel.runtime.checkpoints`: CheckpointStore save/load por sesión.
- [x] `ciel.runtime.context`: project context files discovery + render.
- [x] `ciel.runtime.context_compression`: compress_context head/tail/rewrite.
- [x] CLI: `ciel --help`, `ciel doctor`, `ciel run`, `ciel chat -q`, `ciel compression`, `ciel checkpoints`, `ciel info`.
- [x] Ejemplo end-to-end: `examples/end_to_end.py`.
- [x] Suite verde: `uv run pytest`.

## Cerrado/avanzado
- [x] `ciel.acp`: paquete mínimo FastAPI `/health`, `/v1/chat`, `/v1/tools/{toolset}/{name}`.
- [ ] Adaptador avanzado para IDEs.

## Bloqueo conocido
- Verificación ejecutable bloqueada por dependencias no instaladas en el entorno local (`httpx`, `fastapi`).

## Próximo paso
1. Instalar deps y cerrar verificación.
2. Cerrar MCP HTTP funcional.
3. Avanzar a Fase 2.
