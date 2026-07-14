# Fase 3 — Progreso

Estado actual: en desarrollo ejecutable; suite verde.
Verificación: `uv run pytest -q` pasa.

Código ejecutable entregado y verificado en tests unitarios existentes:
- `ciel.orchestration.spec`: `AgentSpec`, `AgentStep`, `from_yaml`.
- `ciel.orchestration.supervisor`: `Supervisor` con presupuesto y rate-limit.
- `ciel.orchestration.topology`: `TopologyEngine` pipeline/fan-out/debate, rechazo por presupuesto excedido.
- `ciel.orchestration.queue`: `DurableQueue` SQLite WAL.
- `ciel.orchestration.board`: `KanbanBoard`, `BoardTask`, filtros status/assignee/tenant.
- `ciel.orchestration.budget`: `Budget`, `AgentCounter`, `RateLimiter`.
- `ciel.cli.main`: app Typer con subcomandos `swarm` y `board` registrados.
- `ciel.cli.swarm`: comando `swarm run`.
- `ciel.cli.board`: comandos `board add/list/show/assign`.

Pendiente inmediato real:
- Verificar ejecución E2E desde CLI con `swarm_app` y `board_app` directamente.
- Ajustar `tests/orchestration_fase3_test.py` para invocar `swarm_app` y `board_app` sin acoplamientos innecesarios con `ciel.cli.main`.
- Suite completa `.venv/Scripts/python -m pytest -q` verde.
- `docs/ROADMAP.md` y docs finales.

Criterio de cierre de Fase 3:
- Pipeline reproducible desde YAML, presupuesto/rate-limit respetado, 100% tests verdes.
