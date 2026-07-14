# Cierre de sesión — paralelización con subagentes

Fecha: 2026-07-09. Trabajo ejecutado por 3 subagentes en paralelo
(que expiraron por timeout de red sin entregar resumen) y consolidado/
corregido por el agente principal.

Estado final de la suite: **116 passed, 1 skipped** (subió de 109 → 116).
Verificación: `uv run pytest -q` verde.

## 1. Persistencia del KanbanBoard (sqlite) — SUBAGENTE A

`KanbanBoard` ya soportaba SQLite vía `path=`, pero el CLI y el gateway lo
instanciaban en memoria. Cableado:

- `src/ciel/cli/board.py`:
  - Nueva `resolve_db_path(db_flag)` con prioridad
    `--db` > `CIEL_BOARD_DB` (env) > default en cwd.
  - Los 4 comandos (`add`, `list`, `show`, `assign`) ahora usan
    `with KanbanBoard(path=resolve_db_path(db)) as board:`, así la tarea
    sobrevive al proceso.
- `src/ciel/gateway/base.py`:
  - `create_control_app` acepta `board_db_path` y, si está seteado (o hay
    `CIEL_BOARD_DB`), monta el board sobre SQLite; si no, queda en memoria
    (fallback offline/smoke). `/v1/board/list` ahora ve las tareas del CLI.

Verificado E2E: `CIEL_BOARD_DB=/tmp/b.sqlite3 uv run ciel board add t1
--tenant-id acme` y luego en un SEGUNDO proceso
`CIEL_BOARD_DB=/tmp/b.sqlite3 uv run ciel board list --tenant-id acme`
muestra `t1`. Persistencia cross-invocación: OK.

## 2. Streaming SSE (runtime → HTTP + CLI) — SUBAGENTE B

El runtime ya tenía `stream_tokens` / `stream_agent_loop` / provider `stream()`.
Faltaba exponerlo. Entregado:

- `src/ciel/gateway/base.py`: nuevo `POST /v1/agent/run/stream` que usa
  `StreamingResponse` (media_type `text/event-stream`) y emite cada token
  como `data: <token>` cerrando con `data: [DONE]`. Valida `tenant_id`
  (400 si falta), igual que `/v1/agent/run`.
- `src/ciel/cli/main.py`: `ciel chat` gana flag `--stream` que imprime
  fragmentos incrementalmente vía `runtime.stream_tokens` (con fallback a
  chunk único si el proveedor no implementa stream). Agregado
  `_EchoProvider` offline para que el flag funcione sin red.
- Docs: `docs/sdk/README.md` actualizado con el endpoint SSE.

Correcciones del agente principal sobre el trabajo del subagente:
- Bug crítico: `main.py` importaba `from ciel import __version` (faltaba
  un guión bajo) → `ImportError` que rompía TODO el CLI. Corregido a
  `__version__`.
- Bug: `_EchoProvider.complete` hacía `from ciel.providers import
  ChatChoice, ChatResponse`, pero esos símbolos están en `ciel.runtime`.
  Corregido a `from ciel.runtime import ChatChoice, ChatResponse`.

Verificado E2E:
- Gateway: `POST /v1/agent/run/stream` con echo provider → 200, body
  `data: echo:hi\n\ndata: [DONE]\n\n`.
- CLI: `uv run ciel chat --stream -q "di hola"` → imprime `echo:di hola`
  en tiempo real (offline).

## 3. Auditoría y elevación de tests — SUBAGENTE C

- `tests/test_slack_adapter_test.py`: de 4 → 7 tests. Nuevos:
  - `test_enqueue_pushes_message_onto_internal_queue`
  - `test_url_verification_challenge_responds` (router Slack responde al
    handshake `url_verification`)
  - `test_event_callback_message_is_enqueued` (evento `message` se encola)
- `tests/test_streaming_test.py`: de 3 → 5 tests. Nuevos:
  - `test_stream_agent_loop_yields_tool_turn` (itera `ToolLoopResult` con
    tool_calls reales)
  - `test_stream_tokens_handles_empty_sse_body` (body vacío no crashea)

BUG DE PRODUCCIÓN ENCONTRADO Y CORREGIDO (por el agente principal):
- `create_slack_webhook_router` (en `src/ciel/gateway/__init__.py`) hacía
  `await enqueue(message)`, pero `SlackAdapter.enqueue` es SÍNCRONO
  (`put_nowait`). En eventos `event_callback` reales crasheaba con
  `TypeError: 'NoneType' object can't be awaited`.
- El subagente C lo dejó como `@pytest.mark.xfail` (correcto: reportó, no
  arregló sin avisar). El agente principal corrigió la línea a
  `enqueue(message)` (sin await) y subió el test a verde real.

## Archivos modificados en esta sesión

- `src/ciel/cli/board.py` (persistencia CLI)
- `src/ciel/cli/main.py` (stream flag + echo provider + 2 bugfixes)
- `src/ciel/gateway/base.py` (board sqlite + endpoint SSE)
- `src/ciel/gateway/__init__.py` (bugfix await enqueue Slack)
- `tests/test_slack_adapter_test.py` (+3 tests, xfail→pass)
- `tests/test_streaming_test.py` (+2 tests)
- `docs/sdk/README.md` (endpoint SSE documentado)

## Pendiente menor conocido

- `ciel chat --stream` con proveedor remoto (no echo) requiere que el
  provider implemente `stream()`; el echo hace fallback a chunk único.
- No se creó commit (repo sin git). El estado está consistente en disco.
