# Fase 6 — Progreso (Agencia autónoma en bucle)

Estado actual: **Fase 6 ENTREGADA — módulo `agent` (`EventLoop` + `AutonomousAgent`)
ENTREGADO y verificado offline**. Verificación: `uv run pytest tests/` → **153
+ N passed, 1 skipped** (la fase sumó `test_agent_fase6_test.py`). `uv run ciel
loop run` y `uv run ciel loop resume` ejecutan offline.

## Entregables cerrados / verificados

### Módulo `agent` (AutoGen/ADK) — NUEVO
- `src/ciel/orchestration/agent.py`: agencia autónoma en bucle estilo
  AutoGen/ADK, montada SOBRE el `Supervisor` (cada intento de tarea hereda
  retry/timeout/budget por worker) y SOBRE `SessionStore` (estado por tenant).
  - `Task`: unidad de trabajo durable (`goal`, `payload`, `status`,
    `attempts`, `result`, `error`, `snapshot()`/`from_snapshot()`,
    `mark_running`/`mark_succeeded`/`mark_failed`).
  - `EventLoop`: bucle durable con reintentos exponenciales (backoff
    `base_delay_s * 2^(n-1)` capped a `max_delay_s`). `run(task, handler, *,
    run_id)` ejecuta con reintentos y persiste checkpoint tras cada intento;
    `resume(run_id, handler)` rehidrata desde `MemoryStore` y continúa,
    completando la tarea (criterio Fase 6: sobrevive a reinicio). Idempotente
    si el checkpoint ya está `succeeded`/`failed`. Lanza `TaskError` si el
    handler falla SIEMPRE; `EventLoopError` si `resume` no tiene checkpoint.
  - `EventLoopCheckpointStore`: persistencia del estado del loop sobre
    `MemoryStore` (clave `loop:<run_id>`, namespaced; multitenancy nativo:
    `tenant_id=None` → `"__none__"`).
  - `AutonomousAgent`: orquestador de nivel superior. `run_goal(goal, handler, *,
    plan=None)` descompone el objetivo en tareas (una por paso de `plan`, o una
    sola si `plan=None`) y las ejecuta vía `EventLoop`; tras cada tarea completa
    persiste un turno en `SessionStore` (ADK session_state entre ejecuciones).
  - Excepciones: `AgentError`, `EventLoopError`, `TaskError`.
- `src/ciel/cli/loop.py` + registro en `main.py`
  (`app.add_typer(_load_loop_group(), name="loop")`): `ciel loop run <goal>`
  (offline-safe, demo con handler echo local; opciones `--run-id`/`--db`/`--tenant`/
  `--session-id`) y `ciel loop resume --run-id <id> --db <db>` (reanuda tras
  reinicio).
- `src/ciel/orchestration/__init__.py` exporta `Task`, `EventLoop`,
  `EventLoopCheckpointStore`, `EventLoopStep`, `AutonomousAgent`, `AgentError`,
  `EventLoopError`, `TaskError`.
- `tests/test_agent_fase6_test.py`: batería verde (snapshot round-trip, run
  completa en 1 intento, reintento exponencial transitorio, fallo permanente →
  `TaskError`/`failed`, checkpoint save/load, resume tras reinicio, resume
  idempotente, resume sin checkpoint → `EventLoopError`, `run_goal` 1 tarea,
  `run_goal` con plan de 3, integración SessionStore, multitenancy en
  checkpointer).

### Reutilización de la Fase 5 / base
- `Supervisor` (retry/timeout/budget) — cada intento de `EventLoop` es un worker.
- `SessionStore` — `AutonomousAgent` persiste turnos de session por tenant.
- `MemoryStore` — checkpoint store del loop (multitenancy nativo ya resuelto en
  Fase 5 con el sentinel `__none__`).
- `DurableQueue` (SQLite WAL en `queue.py`) queda disponible como backing store
  de larga duración del loop (enlazable por `run_id`/`tenant_id`); la Fase 6 lo
  documenta como reutilizable sin acoplarlo todavía al `EventLoop`.

## Cierre de Fase 6
**Fase 6 CERRADA.** Se cumplen todos los criterios de avance: `EventLoop` ejecuta
una `Task` y tras reinicio (`resume` desde checkpoint en `MemoryStore`) continúa
y la completa; los reintentos exponenciales se activan ante fallo transitorio y
la tarea termina en éxito; `ciel loop run` / `ciel loop resume` funcionan offline;
cada pieza (agent / eventloop) tiene core + CLI + tests verdes y está documentada;
y la suite queda verde.

## Bugs de raíz corregidos (esta sesión)
- Ninguno en código existente. El core nuevo evita dos trampas del patrón:
  1. **Doble reintento Supervisor vs EventLoop**: el `Supervisor` ya hace sus
     propios reintentos (`max_attempts=2` por defecto). Para que `EventLoop`
     controle los reintentos de forma limpia, los tests/cli usan
     `Supervisor(max_attempts=1)` + `EventLoop(max_attempts=N)`. El core no
     asume esto, pero documentarlo evita contar intentos mal.
  2. **Namespacing del checkpoint por session**: el checkpoint se guarda con
     `session_id or run_id`, coherente con `flow`/`root`; `resume` debe usar el
     mismo `--session-id` (o ninguno a ambos) para hallar el checkpoint.

## Pendiente en Fase 6
- [x] `ciel.orchestration.agent`: `EventLoop` durable + `AutonomousAgent`. ✅ ENTREGADO.
- [x] Reintentos exponenciales + `resume` tras reinicio. ✅ ENTREGADO.
- [x] CLI `ciel loop run|resume` offline-safe. ✅ ENTREGADO.
- [x] Tests Fase 6 verdes. ✅ ENTREGADO (`test_agent_fase6_test.py`).
- [x] Documentar `FASE6_PROGRESS.md` + `FASE6_DESIGN.md`. ✅ ENTREGADO.

## Siguiente fase sugerida
Fase 7 — Enterprise duro (RBAC/OIDC, audit inmutable, cost governance): módulos
`ciel.gateway.auth` (OIDC), `ciel.observability.audit` (append-only hash-chain),
`ciel.metrics` (cost por tenant), `ciel security secrets` (Vault/K8s); CLI
`ciel rbac`, `ciel cost`.
