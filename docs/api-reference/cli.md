# `ciel.cli` — Interfaz de línea de comandos

Aplicación Typer que expone el comando `ciel`. El punto de entrada registrado
en PyPI es `ciel.cli.main:app`.

::: ciel.cli
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members:
        - app

::: ciel.cli.main
    options:
      show_root_heading: false
      members: true

::: ciel.cli.root
    options:
      show_root_heading: false
      members: true

::: ciel.cli.chat
    options:
      show_root_heading: false
      members: true

::: ciel.cli.loop
    options:
      show_root_heading: false
      members: true

::: ciel.cli.graph
    options:
      show_root_heading: false
      members: true

::: ciel.cli.flow
    options:
      show_root_heading: false
      members: true

::: ciel.cli.board
    options:
      show_root_heading: false
      members: true

::: ciel.cli.swarm
    options:
      show_root_heading: false
      members: true

::: ciel.cli.cost
    options:
      show_root_heading: false
      members: true

::: ciel.cli.rbac
    options:
      show_root_heading: false
      members: true

::: ciel.cli.scaffold
    options:
      show_root_heading: false
      members: true

::: ciel.cli.skills_cli
    options:
      show_root_heading: false
      members: true

---

## `ciel skills` — gestión de la Skill Library (offline)

Subcomando Typer registrado como `ciel skills`. Toda la operación es
**offline-safe** (sin red ni API keys): opera sobre una `SkillLibrary` en
memoria usando `ciel.runtime.skills_lib`.

```bash
ciel skills list
ciel skills create --name add --description "Suma dos enteros" --code-file add.py
ciel skills verify --name add --test-cases cases.json
ciel skills remove --name add
```

### `ciel skills list`

Lista los skills registrados en la librería en memoria (última versión de cada
nombre), en una tabla Rich con columnas `name` / `category` / `description`. Si
no hay ninguno, imprime `(no skills registered)`.

### `ciel skills create`

Crea un skill desde un archivo de código Python y lo registra.

| Opción | Requerida | Descripción |
|---|---|---|
| `--name` | sí | Nombre del skill. |
| `--description` | sí | Descripción del skill. |
| `--code-file` | sí | Ruta a un `.py` con el código fuente (debe compilar; si no, falla con mensaje y `exit 1`). |
| `--category` | no | Categoría opcional. |

Al registrar, imprime el `sha256` de los 12 primeros caracteres y la categoría.

### `ciel skills verify`

Verifica un skill contra casos de prueba, offline.

| Opción | Requerida | Descripción |
|---|---|---|
| `--name` | sí | Nombre del skill a verificar. |
| `--test-cases` | sí | Archivo JSON: una **lista** de `{"call": {...}, "expect": <valor>}`. |

El verificador ejecuta el código en un namespace aislado, invoca la callable
(nombrada como el skill o la primera callable definida) con `call` y compara el
resultado con `expect`. Imprime `PASS`/`FAIL`; en fallo hace `exit 1`.

```json
[
  {"call": {"a": 2, "b": 3}, "expect": 5},
  {"call": {"a": 0, "b": 0}, "expect": 0}
]
```

### `ciel skills remove`

Elimina un skill de la librería en memoria. `--name` requerido. Imprime `removed`
si existía o `not found` + `exit 1` si no.

> **Nota:** la CLI usa una librería en memoria *fresh* por proceso, por lo que
> `create`/`verify`/`remove` no persisten entre invocaciones separadas. Para
> flujos persistentes usa la API de `ciel.runtime.skills_lib` directamente
> (ver [`docs/guide/skills.md`](../guide/skills.md)).

---

## `ciel reflect` — auto-reflexión e introspección (Fase 19, v0.13)

Subcomando Typer registrado como `ciel reflect`. **Offline-safe** (usa
`MockProvider` por defecto, sin red ni API keys). Reutiliza `ciel.eval.Evaluator`
para medir KPIs de auto-aprendizaje sobre un dataset.

```bash
ciel reflect run --dataset tests/eval/smoke.yaml --provider mock --threshold 0.0
ciel reflect history --name <prompt>
ciel reflect introspect --session <id> [--tenant-id <tenant>]
```

### `ciel reflect run`

Corre un dataset con `MockProvider` (o `--model mock/echo`) y reporta KPIs de
auto-reflexión en una tabla Rich. Si `pass_rate < --threshold`, hace `exit 1`.

| Opción | Requerida | Descripción |
|---|---|---|
| `--dataset` | sí | Ruta al YAML del dataset (formato `ciel.eval.load_dataset`). |
| `--provider` | no | Proveedor evaluable (`mock` por defecto). |
| `--model` | no | Model id (`mock/echo`, `mock/map`, `mock/fixed`). |
| `--mock-response` | no | Respuesta fija (modo `fixed`). |
| `--threshold` | no | Umbral mínimo de `pass_rate` (default `0.8`). |

### `ciel reflect history`

Imprime el `evolution_tree` de un prompt versionado (`ciel.runtime.prompt_versioning.PromptRegistry`),
en una tabla Rich con columnas `versión` / `parent` / `sha256` / `changelog`.
Requiere `--name`; `--tenant-id` opcional (aislamiento multitenant).

### `ciel reflect introspect`

Vuelca los últimos snapshots de `cognitive_state_log` de una sesión
(`ciel.runtime.cognitive_state`). Requiere `--session`; `--tenant-id` y `--limit`
opcionales.

::: ciel.cli.evaluate
    options:
      show_root_heading: false
      members: true

::: ciel.cli.reflect
    options:
      show_root_heading: false
      members: true

