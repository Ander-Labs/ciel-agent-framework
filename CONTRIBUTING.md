# Guía de contribuciones — Ciel Agent Framework

¡Gracias por tu interés en contribuir a **Ciel Agent Framework**! Este documento
explica cómo preparar tu entorno, seguir el estilo del proyecto, ejecutar las
pruebas y enviar tus cambios.

Ciel es un framework SDK + runtime + orquestador para agentes autónomos y
multiagente empresariales, escrito en Python y gestionado con
[`uv`](https://docs.astral.sh/uv/).

---

## Índice

- [Cómo clonar el repositorio](#cómo-clonar-el-repositorio)
- [Configuración del entorno con `uv`](#configuración-del-entorno-con-uv)
- [Estándar de estilo](#estándar-de-estilo)
- [Cómo correr los tests](#cómo-correr-los-tests)
- [Issues](#issues)
- [Pull requests](#pull-requests)
- [Convención de commits](#convención-de-commits)
- [Licencia](#licencia)

---

## Cómo clonar el repositorio

```bash
git clone https://github.com/Ander-Labs/ciel-agent-framework.git
cd ciel-agent-framework
```

Trabajamos sobre la rama `master`. Crea una rama de feature a partir de ella
antes de empezar:

```bash
git checkout -b mi-feature/master
```

> Usa un nombre de rama descriptivo, por ejemplo `fix/approval-timeout`,
> `feat/graph-resume` o `docs/contributing-es`.

---

## Configuración del entorno con `uv`

El proyecto usa [`uv`](https://docs.astral.sh/uv/) como gestor de dependencias y
entorno. Si no lo tienes instalado:

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Sincroniza el entorno (crea el `.venv` e instala dependencias, incluidas las de
desarrollo):

```bash
uv sync
```

Para instalar también grupos opcionales (docs, etc.):

```bash
uv sync --all-extras        # todas las extensiones
uv sync --extra gateway     # solo un grupo concreto
```

Ejecuta cualquier comando dentro del entorno con `uv run`, sin necesidad de
activar el venv manualmente:

```bash
uv run python examples/end_to_end.py
uv run ciel --help
uv run pytest
```

Para trabajar en modo editable (desarrollo del propio paquete):

```bash
uv pip install -e ".[dev,gateway]"
```

---

## Estándar de estilo

- **Linter/formatter**: el proyecto usa [`ruff`](https://docs.astral.sh/ruff/).
  La configuración vive en `pyproject.toml` (`[tool.ruff]`), con
  `line-length = 100` y selección de reglas `E, F, I, UP, B, SIM`.
- **Python**: requiere `>= 3.11`. El `target-version` de ruff apunta a 3.14.
- **Imports**: ordenados automáticamente por `ruff` (`I`). No dejes imports
  sin usar.
- **Tipado**: usa type hints en firmas públicas. El proyecto depende de
  Pydantic v2.
- **Documentación**: en **español**, coherente con el resto del repositorio
  (`docs/` está en español).
- **Convenciones de código**:
  - Sigue los lineamientos del charter en `docs/CHARTER.md` (harness-first,
    enterprise-by-default, interface-first).
  - Las tools deben usar la firma oficial de callable:
    `callable_(arguments, *, tool_call_id, tenant_id) -> ToolResult | dict | Any`.

Antes de commitear, pasa el linter:

```bash
uv run ruff check .
uv run ruff format .      # si aplica
```

---

## Cómo correr los tests

El proyecto usa `pytest` (configurado en `pyproject.toml` con
`testpaths = ["tests"]`). Para ejecutar toda la suite:

```bash
uv run pytest
```

Comandos útiles:

```bash
uv run pytest tests/                 # todo
uv run pytest tests/test_agent.py    # un archivo
uv run pytest tests/test_agent.py::test_foo   # un test concreto
uv run pytest -k "graph"            # por nombre
```

Los tests están diseñados para ser **offline-safe** (usan `DummyProvider`,
`MockProvider` o providers echo de respaldo), de modo que no requieren API keys
ni red. Verifica que pasen en local antes de abrir un PR.

> Build de documentación (opcional): `uv run mkdocs build --strict`.

---

## Issues

Antes de abrir un issue, revisa que no exista uno similar en
[Issues](https://github.com/Ander-Labs/ciel-agent-framework/issues).

Al abrir un issue, incluye la mayor información posible:

- **Tipo**: bug, feature, documentación, pregunta o mejora.
- **Contexto**: qué intentabas hacer y por qué.
- **Reproducción** (para bugs): pasos mínimos, versión de `ciel`
  (`uv run ciel --version`), versión de Python y de `uv`.
- **Comportamiento esperado vs. observado**.
- **Logs / trazas** relevantes (evita pegar secretos o API keys).

---

## Pull requests

1. Asegúrate de haber partido de `master` actualizado.
2. Mantén el PR enfocado en un solo cambio lógico; prefiere PRs pequeños y
   atómicos.
3. Incluye/actualiza tests que cubran tu cambio.
4. Actualiza la documentación (`docs/`) si afecta la API o el comportamiento.
5. Verifica localmente:
   ```bash
   uv run ruff check .
   uv run pytest
   ```
6. En la descripción del PR explica **qué** cambiaste y **por qué**, y enlaza
   el issue relacionado (ej. `Closes #123`).
7. Responde a los comentarios de revisión de forma puntual.

Los PRs se integran en `master` tras revisión y que la CI pase.

---

## Convención de commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/). El formato
es:

```
<tipo>[opcional: ámbito]: <mensaje breve en español>

[cuerpo opcional]
[pie opcional: Closes #123]
```

Tipos permitidos:

| Tipo       | Uso                                                        |
|------------|------------------------------------------------------------|
| `feat`     | Nueva funcionalidad                                        |
| `fix`      | Corrección de bug                                          |
| `docs`     | Documentación (`docs/`, README, CONTRIBUTING)             |
| `style`    | Formato/estilo sin cambio de comportamiento               |
| `refactor` | Refactor sin cambio de comportamiento externo             |
| `test`     | Tests o infra de testing                                   |
| `chore`    | Tareas de mantenimiento (build, deps, CI)                 |
| `perf`     | Mejora de rendimiento                                      |

Ejemplos:

```
feat(gateway): añade router de webhook para Discord
fix(runtime): corrige timeout de approval en GraphNode
docs: agrega guía de contribuciones en español
```

El mensaje debe estar en **español** y ser imperativo y conciso.

---

## Licencia

Ciel Agent Framework se distribuye **únicamente** bajo la
**GNU Affero General Public License v3 (AGPL-3.0-or-later)**. Al contribuir,
aceptas que tu código se publique bajo esta misma licencia. El texto completo
está en el archivo [`LICENSE`](LICENSE).

---

¿Dudas? Abre un issue o un discussion y con gusto te ayudamos a encaminar tu
contribución. ¡Te leemos!
