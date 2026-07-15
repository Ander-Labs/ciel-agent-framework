# Prompt de continuación — LOOP (Ciel Agent Framework)

> Prompt autocontenido para retomar el trabajo en la próxima sesión. Es
> complementario a `docs/Prompt.md` (orquestación maestra). Documenta el
> ESTADO REAL al cierre de la sesión 2026-07-15 y las tareas pendientes
> verificadas. Úsalo tal cual: un agente puede ejecutarlo sin re-explorar.

---

## 0. Contexto del repo (verificado al cierre)

- **Repo:** `A:\Apps\Agents\ciel-agent-framework` (local) = `Ander-Labs/ciel-agent-framework` (GitHub).
- **Rama de trabajo:** `master` (NO `main` — los workflows `ci.yml`/`release.yml` originales usaban `main` y por eso nunca disparaban; ya corregido, ver §2).
- **Paquete PyPI:** `mana-ciel` v0.3.0 publicado (import `ciel`, CLI `ciel`). requires-python `>=3.11`.
- **Releases GitHub vivos:** `v0.3.0` (Fase 9) y `v0.2.0` (Fase 8) — ambos HTTP 200.
- **Fases CERRADAS:** 0–9. Fase 8 (Deploy HA + observabilidad) y Fase 9 (Extensibilidad) entregadas y publicadas.
- **Doc oficial VIVA:** https://ander-labs.github.io/ciel-agent-framework/ — home, guía, arquitectura, runbooks, roadmap, upgrade y referencia de API (mkdocstrings) responden 200.
- **Toolchain:** `uv` (sync con `--all-extras` para correr la suite completa). `pytest` con `addopts=-q` en pyproject (el summary se ve con `tr '\r' '\n'` sobre el log o `--tb=line`).

## 1. Estado de verificación (al cierre)

| Check | Comando | Resultado |
|---|---|---|
| Tests suite | `uv sync --all-extras && uv run pytest tests/` | 230 passed, 2 skipped |
| Doc build | `uv run mkdocs build --strict` | exit 0, `site/index.html` generado |
| Doc site | `curl https://ander-labs.github.io/ciel-agent-framework/` | 200 (todas las secciones) |
| CI GitHub | run de `ci.yml` en push a `master` | `completed success` |
| Docs deploy | run de `docs.yml` en push a `master` | `completed success` |
| Release GitHub | run de `release.yml` en tag `v*` | `completed success` (publica a PyPI) |

## 2. Correcciones YA APLICADAS (no repetir)

1. **`ci.yml`**: `branches: [main]` → `[master]` (push + PR). `uv sync --extra gateway --extra acp --extra dev` → `uv sync --all-extras` (la suite completa necesita todas las extras o hay `ImportError` en collección).
2. **`pyproject.toml`**: URL de Changelog `blob/main` → `blob/master`.
3. **`docs/CI.md`**: URL repo corregida (`Ander-Labs/ciel-agent-framework`), rama `master`, `requires >=3.11`, `sync --all-extras`, sección de publish actualizada a "habilitado" (coherente con `release.yml` real, que SÍ tiene el job `publish` activo).
4. **`docs.yml`** (nuevo): build + `mkdocs build --strict` + deploy a GitHub Pages (`gh-pages`) en push a `master`. No colisiona con `release.yml` (ese solo en tags `v*`).
5. **GitHub Pages habilitado** vía API (source `gh-pages` / `/`).
6. **`mkdocs.yml`**: nav completo + `search` + mkdocstrings + `exclude_docs` para aislar doc interna. Home en `docs/index.md` (no `guide/index.md`, que se eliminó por redundante).
7. **`docs/roadmap.md` / `docs/upgrade.md`**: páginas públicas (renombradas a minúsculas en git para portabilidad Linux).
8. **`docs/dev/README.md`**: marca `docs/dev/` como diario interno (no publicado). **`docs/Prompt.md`**: advertencia de uso interno.
9. **Bug OTel raíz** (Fase 8): `init_tracing` fuerza el provider al slot global (`trace._TRACER_PROVIDER`) para que `span_count()` refleje el conteo real; `current_tracer()` usa `_last_provider`. (Commit `ce76e86`.)

## 3. Pendientes REALES descubiertos (bajo prioridad, decidir antes de actuar)

- **[Menor / ruido CI]** `mkdocs build` emite warnings "The following pages exist in the docs directory, but are not included in the nav" para la doc interna (`docs/dev/*`, `docs/Prompt.md`, `docs/CHARTER.md`, `docs/CI.md`, `docs/UPGRADE_v0.3.0.md`). `exclude_docs` no los silencia del todo (mkdocs los lista antes de aplicar exclude). NO rompen el deploy (exit 0 bajo `--strict`). Si se quiere CI 100% limpio: mover esos archivos fuera de `docs/` (ej. a `docs-internal/`) o listarlos en el nav. Refactor mayor — dejar salvo que el usuario lo pida.
- **[Decisión de producto] Fase 10**: no definida. Opciones sugeridas (elegir UNA o pedir al usuario):
  - (a) Pulido/adoption: ejemplos end-to-end en `examples/`, tutorial público, benchmarks de HPA.
  - (b) Apertura comunitaria: issues de seguimiento en GitHub derivados de los runbooks, plantillas de PR/issues.
  - (c) Hardening: tests de integración reales contra providers (no mock), fuzzing de tool-callables.
- **[Verificación]** Confirmar que el run de `ci.yml` en GitHub quedó `success` tras el push de `6e3ff3b` (YA VERIFICADO: `completed success`).

## 4. LOOP de continuación (ejecutar para la próxima pieza)

1. **Leer estado:** este archivo + `docs/dev/INDEX.md` + `CHANGELOG.md` (sección superior).
2. **Decidir fase/tarea** (si es Fase 10, acordar alcance con el usuario antes de escribir código).
3. **Usar subagentes en PARALELO** (`delegate_task`, hasta 3) para trozos independientes:
   - ej.文档ación, tests, ejemplos, CI — cada uno aislado, sin commitear; el orquestador integra y verifica.
4. **Verificar SIEMPRE antes de commit:**
   - `uv sync --all-extras`
   - `uv run pytest tests/` → debe quedar en verde (230+ passed).
   - `uv run mkdocs build --strict` → exit 0 si tocaste docs.
5. **Documentar** en `docs/dev/INDEX.md` y, si aplica, `docs/dev/FASE{N}_PROGRESS.md`.
6. **Commit + push a `master`** (esto dispara `ci.yml` y `docs.yml` automáticos).
   - Si es release: `git tag v0.X.0` + `git push origin v0.X.0` (dispara `release.yml` → PyPI). Recordar el QUIRK: en Windows `uv publish` con token por env puede fallar por CRLF; en el runner de GitHub (Linux) funciona con `UV_PUBLISH_TOKEN`.
7. **No preguntar** si la decisión es segura/óptima (criterio del usuario). Si hay ambigüedad de producto (p.ej. qué es Fase 10), preguntar UNA vez.

## 5. Comandos de verificación rápida (copiar-pegar)

```bash
# entorno completo
uv sync --all-extras

# tests
uv run pytest tests/ -p no:cacheprovider -q -W ignore 2>&1 | tr '\r' '\n' | grep -E "[0-9]+ passed|[0-9]+ failed"

# doc build (lento ~3 min por mkdocstrings; usar timeout 500)
uv run mkdocs build --strict

# doc site
curl -s -o /dev/null -w "%{http_code}\n" https://ander-labs.github.io/ciel-agent-framework/

# workflows en GitHub (requiere token del credential manager de Windows)
TOKEN=$(printf 'protocol=https\nhost=github.com\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')
curl -s -H "Authorization: Bearer $TOKEN" "https://api.github.com/repos/Ander-Labs/ciel-agent-framework/actions/runs?per_page=5"
```

## 6. Reglas duras

- Rama: `master` (nunca `main`).
- No commitear ni pushear sin verificar tests + (si aplica) doc build.
- No recrear `docs/guide/index.md` (su contenido ya está en `docs/index.md`).
- Mantener `docs/dev/` como diario interno (excluido del sitio vía `exclude_docs`).
- PyPI: solo publicar en tags `v*`; el token va en secreto `CIEL_PYPI_TOKEN`.
