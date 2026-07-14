# Fase 3 — Prompt para continuar después

## Contexto
Continúa Fase 3 del Ciel Agent Framework en `A:\Apps\Agents\ciel-agent-framework`.
- Intérprete: `.venv/Scripts/python`
- Verificación: `pytest -q`
- Idioma: español

## Estado actual
- `AgentSpec.from_yaml`, `Supervisor` con budget/rate-limit, `TopologyEngine` pipeline/fan-out/debate y `KanbanBoard` están funcionales.
- Tests unitarios de orchestration existentes verdes.
- `tests/orchestration_fase3_test.py` tiene tests Fase 3 que no pasan porque la suite prueba la CLI usando `runner.invoke(app, ["swarm", "run" ...])`, que regresa 2 en Click 8.4 por `get_group_from_info` al recorrer módulos de `ciel.cli`; no se puede probar `swarm`/`board` con subcomandos anidados hasta resolver este acoplamiento.
- `ciel.cli.main` importa `swarm_app` y `board_app` para registrar `app.add_typer(...)`.

## Bloqueo exacto a resolver
Click/Typer 8.4 falla al inspeccionar el grupo `swarm` desde `main.py` porque no expone `registered_commands` directo en el módulo importado. Necesitás:
1. Quitar la importación de `swarm_app`/`board_app` dentro de `ciel.cli.__init__` o `main.py`.
2. Aislar los tests de la CLI Fase 3 para usar las apps `swarm_app`/`board_app` directamente, sin pasar por `ciel.cli.main`.

## Tareas pendientes inmediatas
1. Revisar `src/ciel/cli/main.py`, `src/ciel/cli/__init__.py`, `src/ciel/cli/swarm.py`, `src/ciel/cli/board.py`.
2. Correr `python - <<'PY'\nfrom cielo.cli.main import app\nfrom typer.testing import CliRunner\nrunner = CliRunner()\nprint(runner.invoke(app, ['swarm', 'run', '--spec', 'tests/fixtures/spec.yaml', '--max-tools', '8', '--seconds', '5', '--rate-limit', '0']).exit_code)\nprint(runner.invoke(app, ['board', 'list', '--db', 'ciel_board.sqlite']).exit_code)\nPY`.
3. Si persiste, eliminar la invocación en tests y reescribir `tests/orchestration_fase3_test.py` para invocar `swarm_app`/`board_list` directamente con un SQLite tmp, usando validaciones de texto/exit code.
4. Eliminar TODO ingame flow en Fase 3; dejar solo Fase 4 pendiente.
5. Confirmar suite verde con `.venv/Scripts/python -m pytest -q`.
6. Actualizar `docs/dev/FASE3_PROGRESS.md` y `docs/ROADMAP.md` solo después de verde.

## Dónde están los archivos relevantes
- CLI: `src/ciel/cli/main.py`, `src/ciel/cli/swarm.py`, `src/ciel/cli/board.py`
- Orchestration: `src/ciel/orchestration/__init__.py`, `supervisor.py`, `topology.py`, `budget.py`, `board.py`, `queue.py`
- Tests: `tests/orchestration_fase3_test.py`, `tests/orchestration_test.py`, `tests/orchestration_topology_test.py`
- Docs: `docs/dev/FASE3_PROGRESS.md`, `docs/ROADMAP.md`, `docs/dev/TASKS.md`

## Criterio de cierre Fase 3
Suite completa verde (`pytest -q`) y pipeline reproducible de 3 agentes desde YAML con presupuesto y rate-limit activo.
