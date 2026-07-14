# Ciel — Diseño Fase 6 (Agencia autónoma en bucle)

Fecha: 2026-07-13. Estado base verificado: **153 passed, 1 skipped** (Fase 5
CERRADA, módulos `graph`, `flows`, `chat`, `root`, `session` entregados). Esta
fase añade la **agencia autónoma en bucle** (AutoGen/ADK): un `EventLoop`
durable con reintentos exponenciales + checkpoint sobre `MemoryStore`, y un
`AutonomousAgent` de nivel superior que descompone objetivos en tareas y las
ejecuta persistiendo session state.

## 1. Tesis de la fase

La orquestación best-of-breed de Fase 5 modela *flujos* (grafo, flows, group
chat, routing). La Fase 6 cierra el ciclo: un **agente que se ejecuta a sí
mismo en bucle** frente a una tarea de larga duración, sobrevive a reinicios y
reintenta ante fallos transitorios. Esto es lo que ADK (`Agent` + loop) y
AutoGen (GroupChatManager con terminación) aportan, pero aquí montado sobre el
`Supervisor` y el `MemoryStore` ya existentes — sin reimplementar retry,
timeout, budget ni multitenancy.

Diferenciador: **loop durable + checkpoint por tenant + reintento exponencial
con resume tras reinicio**, todo OFFLINE-SAFE (handlers locales / echo
provider, sin red).

## 2. Componentes (best-of-breed → ciel)

| Patrón de mercado        | En ciel (Fase 6)                                   | Origen sugerido |
|--------------------------|-----------------------------------------------------|-----------------|
| AutoGen event loop       | `EventLoop.run` / `EventLoop.resume`               | AutoGen         |
| ADK agent loop           | `AutonomousAgent.run_goal`                          | ADK             |
| Reintento exponencial    | backoff `base * 2^(n-1)` (capped)                   | estándar        |
| Checkpoint + resume       | `EventLoopCheckpointStore` sobre `MemoryStore`     | LangGraph       |
| Sesión entre turnos      | `AutonomousAgent` + `SessionStore` (ADK session)   | ADK             |
| Cola durable de fondo    | `DurableQueue` (SQLite WAL) reutilizable           | (ya en queue.py)|

## 3. Diseño del módulo `ciel.orchestration.agent`

Montado SOBRE `Supervisor` (retry/timeout/budget por worker) y `SessionStore`
(estado por tenant). Todo estado persiste con `(tenant_id, session_id, key)`
vía `MemoryStore` (multitenancy nativo: `tenant_id=None` → `"__none__"`).

### 3.1 `Task` (dataclass durable)
Estado de una unidad de trabajo:
- `goal: str`, `payload: dict`, `id: str`, `status` (`pending`/`running`/`succeeded`/`failed`)
- `attempts: int`, `result: Any`, `error: Optional[str]`
- `snapshot()` / `from_snapshot()` para (de)serializar a dict JSON.
- `mark_running()` / `mark_succeeded(result)` / `mark_failed(error)`.

### 3.2 `EventLoop` (durable, reintentos exponenciales)
```
EventLoop(supervisor=None, checkpointer=None, tenant_id=None, session_id=None,
          max_attempts=5, base_delay_s=0.05, max_delay_s=2.0, jitter=False)
```
- `async run(task, handler, *, run_id=None) -> Task`
  - Ejecuta `task` vía `Supervisor.run` (hereda retry/timeout/budget). Si el
    handler hace `raise`, el loop aplica backoff y reintenta hasta `max_attempts`.
  - Tras CADA intento persiste checkpoint (`loop:<run_id>`) si hay `checkpointer`.
  - Éxito → `task.status="succeeded"`, devuelve `task`.
  - Agotados los reintentos → lanza `TaskError`, `task.status="failed"`.
- `async resume(run_id, handler) -> Task`
  - Requiere `checkpointer`. Rehidrata la `Task` del checkpoint y continúa los
    reintentos. Cumple el **criterio de avance Fase 6**: tras reinicio, el loop
    reanuda y COMPLETA la tarea.
  - Si el checkpoint ya dice `succeeded`/`failed`, devuelve la tarea tal cual
    (idempotente, no re-ejecuta).
  - Sin checkpoint → `EventLoopError`.

### 3.3 `AutonomousAgent` (orquestador de nivel superior)
```
AutonomousAgent(name="autonomous", supervisor=None, checkpointer=None,
                session_store=None, tenant_id=None, session_id=None, max_attempts=5)
```
- `async run_task(task, handler) -> Task`
- `async run_goal(goal, handler, *, plan=None) -> List[Task]`
  - `plan=None` → una sola tarea con `goal`. `plan=[...]` → una tarea por paso.
  - Tras cada tarea completada persiste un turno en `SessionStore` (ADK
    session_state entre ejecuciones del agente) si está disponible.
- OFFLINE-SAFE: planner/handlers locales sobre `task.payload`; sin red ni
  proveedor.

### 3.4 `EventLoopCheckpointStore`
Persistencia del estado del loop sobre `MemoryStore` (clave `loop:<run_id>`,
namespaced; multitenancy nativo). `save(run_id, loop_state, task, tenant_id,
session_id)` / `load(...)`.

## 4. CLI (`ciel loop`)
- `ciel loop run <goal>` — ejecuta un agente autónomo offline sobre el objetivo
  (handler echo local). Opciones `--run-id` / `--db` (checkpointer) / `--tenant`
  / `--session-id`. Con `--db` el run queda persistido para `resume`.
- `ciel loop resume --run-id <id> --db <db>` — reanuda un loop interrumpido
  desde su último checkpoint (simula reinicio de proceso).

## 5. Criterio de avance — Fase 6 (cuándo cerrarla)

- [x] `EventLoop` ejecuta una `Task` autónoma y, tras reinicio (resume desde
      checkpoint en `MemoryStore`), continúa y la completa.
- [x] Reintentos exponenciales se activan ante fallo transitorio y la tarea
      eventualmente termina en éxito.
- [x] `ciel loop run` / `ciel loop resume` funcionan offline.
- [x] Cada pieza (agent / eventloop) tiene core + CLI + tests verdes y está documentada.
- [x] Suite verde (165 passed base Fase 5+6, 194 incl. Fase 7).
