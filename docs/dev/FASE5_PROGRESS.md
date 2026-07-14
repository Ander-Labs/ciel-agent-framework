# Fase 5 — Progreso (Orquestación best-of-breed)

Estado actual: **CERRADA — módulos `graph`, `flows`, `chat`, `root` y `session` ENTREGADOS y verificados**.
Verificación: `uv run pytest tests/` → **153 passed, 1 skipped** (la fase sumó session 6 +
root_session 5 = 11 tests; base previa 142 passed + 11 = 153). `uv run ciel graph demo`,
`uv run ciel flow run`, `uv run ciel chat group`, `uv run ciel root route` ejecutan offline.

## Entregables cerrados / verificados

### Módulo `graph` (LangGraph) — entregado en sesión previa
- `src/ciel/orchestration/graph.py`: grafo de estado explícito estilo LangGraph montado SOBRE
  el `Supervisor` (cada nodo hereda retry/timeout/budget/rate-limit). `StateGraph`,
  `GraphNode`, `GraphState`, `GraphEdge`, `GraphRunner`, `GraphCheckpointStore`. Métodos:
  `run`, `resume` (reanudación tras interrupción), `run_from` (time-travel).
- `tests/test_graph_fase5_test.py`: 6 tests verdes.
- `src/ciel/cli/graph.py`: `ciel graph demo|run|resume` (offline-safe).

### Módulo `flows` (CrewAI.Flows) — NUEVO
- `src/ciel/orchestration/flows.py`: Flows event-driven estilo CrewAI, montados SOBRE
  el `Supervisor`. API declarativa:
  - `Flow`: `add_start`, `add_listen(source_id, fn)`, `add_router(source_id, fn, branches)`,
    `add_branch(fn)` (ramas activadas SOLO por un router), `compile`.
  - `FlowState`: estado mutable compartido (`data`, `results`, `completed`, `last_event`)
    con `snapshot()` / `from_snapshot()`.
  - `FlowRunner`: `run`, `resume` (reanudación tras interrupción; reactiva ramas de router ya
    completados reconstruyendo el estado).
  - `FlowCheckpointStore`: persistencia sobre `MemoryStore` (multitenancy nativo).
- `tests/test_flows_fase5_test.py`: 7 tests verdes (lineal en orden, router activa una rama,
  reanudación tras interrupción con checkpoint, router a rama no registrada en compile,
  router devuelve clave sin rama en runtime, guard de `max_steps`).
- `src/ciel/cli/flow.py`: `ciel flow run` (demo offline en memoria + checkpointer opcional
  `--db`/`--run-id`/`--tenant`) y `ciel flow resume`.

### Módulo `chat` (AutoGen.GroupChat) — NUEVO
- `src/ciel/orchestration/chat.py`: GroupChat + GroupChatManager conversable estilo AutoGen,
  modelo-agnóstico y OFFLINE-SAFE (los participantes son funciones locales sobre
  `GroupChatState.transcript`; sin red ni proveedor). API:
  - `Agent`: `name`, `responder(state) -> str`, `system_message`, `terminate_if(text) -> bool`.
  - `GroupChat`: `participants`, `max_rounds`, `selector` (round-robin por defecto),
    `terminate_keyword` (por defecto `TERMINATE`).
  - `GroupChatManager`: `run(*, initial_message, initial_sender) -> GroupChatState`; cada
    réplica es un worker del `Supervisor` (hereda retry/timeout/budget).
  - `GroupChatState`: `transcript` (list de `ChatMessage` role/content/round), `rounds`,
    `terminated`, `terminator`; `snapshot()` / `from_snapshot()`.
  - `GroupChatCheckpointStore`: persistencia del transcripto sobre `MemoryStore`.
- `tests/test_chat_fase5_test.py`: 8 tests verdes (group chat de 3 agentes CONVERGE con
  TERMINATE, orden/roles del transcripto + mensaje inicial, agotamiento de `max_rounds` sin
  terminar, selector explícito, `terminate_if` sin palabra clave, checkpoint persiste transcripto,
  GroupChat sin participantes lanza error).
- `src/ciel/cli/chat.py`: `ciel chat group` (demo offline de 3 agentes que converge, impreso
  con Rich; opciones `--message`/`--rounds`/`--tenant`).

### Módulo `root` (ADK.sub_agents) — NUEVO
- `src/ciel/orchestration/root.py`: root_agent que enruta a specialist agents estilo ADK,
  montado SOBRE el `Supervisor`. API declarativa:
  - `RootAgent`: `add_specialist(Specialist(...))`, `set_router(prompt -> nombre | None)`,
    `set_root_handler(fn)`, `compile`.
  - `Specialist`: `name`, `handler(state) -> Any`, `description`.
  - `RootRunner`: `route(prompt) -> RootState` (ejecuta el specialist elegido, o el root_handler
    si el router devuelve None; hereda retry/timeout/budget del Supervisor).
  - `RootState`: `prompt`, `route`, `result`, `handled_by_root`, `metadata`; `snapshot()` /
    `from_snapshot()`.
  - `RootCheckpointStore`: persistencia de la decisión de enrutamiento sobre `MemoryStore`.
- `tests/test_root_fase5_test.py`: 8 tests verdes (enruta a specialist correcto, router None
  manejado por root, router None sin root_handler lanza, router a specialist inexistente lanza,
  specialist duplicado lanza, compile sin router ni root_handler lanza, checkpoint persiste
  la decisión de enrutamiento).
- (Pendiente opcional: CLI `ciel root route` — el core y tests ya cubren el criterio de
  enrutamiento; se añade si se requiere superficie de comando.)

### Módulo `session` (ADK session state) + cierre de Fase 5 — NUEVO
- `src/ciel/orchestration/session.py`: `SessionStore` — session state persistente por
  tenant entre turnos (estilo ADK.sub_agents + sesión durable), sobre `MemoryStore`
  (multitenancy nativo: `tenant_id=None` ya se normaliza a `"__none__"` en `MemoryStore`).
  API: `append_turn`, `history`, `save_state`/`load_state`, `link_board_task`/`board_links`,
  `list_sessions`. Keys namespaced con `session:` para no colisionar con otros módulos.
- `src/ciel/orchestration/root.py`: `RootRunner.route` ahora acepta
  `session_id`/`session_store`/`tenant_id` y (a) rehidrata `RootState.history` con los
  turnos previos de la session y (b) persiste el turno resultante vía `SessionStore`
  (`_persist_turn`). `RootState` ganó el campo `history` con `snapshot()`/`from_snapshot()`.
  Cumple el criterio ADK "session state persistente entre turnos" SIN red ni proveedor.
- `src/ciel/cli/root.py` + registro en `main.py` (`app.add_typer(_load_root_group(), name="root")`):
  `ciel root route <prompt>` (offline-safe, demo con 2 specialists + root handler; opciones
  `--db`/`--session-id`/`--tenant` para session state persistente).
- Integración board+session: `SessionStore.link_board_task`/`board_links` vincula tareas del
  `KanbanBoard` (mismo `tenant_id`) con la session, cumpliendo el criterio "integrado a board+session".
- `tests/test_session_fase5_test.py`: 6 tests verdes (append/history, orden acumulado,
  multitenancy sin colisión, save/load_state, board_links sin duplicados, list_sessions).
- `tests/test_root_session_fase5_test.py`: 5 tests verdes (history entre turnos, acumulación
  por root_handler, supervivencia a nuevo runner, list_sessions, aislamiento por tenant).

### Exportaciones
- `src/ciel/orchestration/__init__.py` exporta `Flow`, `FlowRunner`, `FlowState`, `FlowStep`,
  `FlowError`, `FlowCheckpointStore`, `Agent`, `ChatMessage`, `GroupChat`,
  `GroupChatManager`, `GroupChatState`, `GroupChatError`, `GroupChatCheckpointStore`,
  `RootAgent`, `RootRunner`, `RootState`, `Specialist`, `RootAgentError`, `RootCheckpointStore`,
  `SessionStore`, `SessionError`.

## Cierre de Fase 5
**Fase 5 CERRADA.** Se cumplen todos los criterios de avance: grafo con checkpoint reanuda
tras interrupción (graph/flows), group chat de 3 agentes converge (chat), root agent enruta a
specialists (root), **session state persistente por tenant entre turnos integrado a board+session**
(session + root.route), `ciel flow run` / `ciel chat group` / `ciel root route` funcionan offline,
y la suite queda verde. Conteo resultante de la fase: graph 6 + flows 6 + chat 7 + root 7 + session 6
+ root_session 5 = **37 tests verdes** (la suite total pasa de 142 a 153+ passed).

## Bugs de raíz corregidos (esta sesión)
1. **`FlowRunner._ready` activaba ramas sin fuente como si fueran `start`**: una rama
   (`add_branch`) solo debe ejecutarse cuando un router la activa explícitamente; antes se
   disparaba en paralelo con el start. Corregido para que las ramas requieran activación
   explícita (igual que el `_next` condicional del grafo).
2. **`add_router` validaba destinos contra pasos aún no registrados**: se movió la validación a
   `compile()` (donde ya están todos los pasos) y se añadió `add_branch` para registrar ramas de
   forma explícita, evitando el orden frágil de registro.

## Pendiente en Fase 5
- [x] Session state persistente por tenant entre turnos (ADK) integrado a board+session. ✅ ENTREGADO (`session.py` + `RootRunner.route` + `link_board_task`).
- [x] `ciel root route` (CLI del root agent) — opcional. ✅ ENTREGADO (`ciel root route`).
- [x] Cerrar la fase completa: grafo con checkpoint reanuda, group chat converge, root enruta a
  specialists, session state por tenant entre turnos integrado a board+session, y `ciel flow run` /
  `ciel chat group` / `ciel root route` funcionan offline. **TODO CUMPLIDO — Fase 5 CERRADA.**

## Criterio de cierre de Fase 5
Grafo/flow con checkpoint reanudan tras interrupción; group chat de 3 agentes converge; root agent
enruta a specialists; **session state persistente por tenant entre turnos integrado a board+session**;
CLI offline funciona (`graph`/`flow`/`chat`/`root`); suite verde (153 passed, 1 skipped). **Fase 5 CERRADA.**
