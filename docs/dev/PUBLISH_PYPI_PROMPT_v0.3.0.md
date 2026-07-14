# Prompt listo para publicar v0.3.0 en PyPI (mana-ciel)

Este archivo es un **guion de ejecución** preparado mientras esperamos el
`CIEL_PYPI_TOKEN`. Cuando el usuario pase el token, se ejecuta el flujo de abajo.
NO contiene el token (se obtiene por fuera, ver pasos).

Proyecto: Ciel Agent Framework
- PyPI distribution name: `mana-ciel`
- Import interno: `ciel` · CLI: `ciel` · requires-python >= 3.11
- Versión a publicar: `0.3.0` (ya tagueada localmente como `v0.3.0`, commit `9b2846a`)
- Repo: https://github.com/Ander-Labs/ciel-agent-framework
- Estado verificado: `uv run pytest tests/` → 230 passed, 2 skipped
- Artifacts locales ya generados en `dist/`: `mana_ciel-0.3.0-py3-none-any.whl`, `mana_ciel-0.3.0.tar.gz`

## Pre-requisitos (lo que el usuario debe proveer)
1. `CIEL_PYPI_TOKEN`: API token de PyPI con permiso de subida para el proyecto
   `mana-ciel`. Formato: `pypi-xxxxxxxx` (token de cuenta o de proyecto).
2. Confirmación de que el usuario ya creó el repo secret en GitHub
   (Settings → Secrets → Actions → `CIEL_PYPI_TOKEN`) O bien que autoriza
   publicar localmente con `uv publish --token <token>`.

## Pasos de ejecución (prompt para el agente / paso a paso)
1. Verificar estado local:
   - `git status` limpio salvo cambios de docs/CI.
   - `git tag` incluye `v0.3.0`.
   - `ls dist/` contiene `mana_ciel-0.3.0-py3-none-any.whl` y `.tar.gz`.
2. (Si el token se provee localmente) Publicar con uv:
   - `uv publish --token "$CIEL_PYPI_TOKEN" dist/*`  (o `uvx twine upload dist/*`).
   - Confirmar respuesta HTTP 200 / "Uploading ... done".
3. (Si el token es un GitHub secret) Empujar tag + workflow:
   - `git push origin master`
   - `git push origin v0.3.0`
   - Esto dispara `.github/workflows/release.yml` (job `publish` ya habilitado en
     este commit) que hace `uv publish` con `UV_PUBLISH_TOKEN=${{ secrets.CIEL_PYPI_TOKEN }}`.
4. Verificar publicación:
   - `pip install --quiet --upgrade mana-ciel==0.3.0` en entorno limpio, o
   - `curl -s https://pypi.org/pypi/mana-ciel/json | python -c "import sys,json;print(json.load(sys.stdin)['info']['version'])"`
     debe imprimir `0.3.0`.
5. Post-publicación (solo si aplica): crear GitHub Release desde `v0.3.0`
   con notas tomadas de `CHANGELOG.md` sección `## [0.3.0]`, incluyendo el
   binario de los wheels. (Requiere `gh` o hacerlo desde la web; `gh` NO está
   instalado en este entorno — instalar o usar la UI.)

## Notas de seguridad
- El token NUNCA se escribe en archivos del repo ni en commits. Solo vive en el
  secret de GitHub o en la variable de entorno efímera del shell.
- No se commitea ningún `.env` ni `secrets.yaml` (ya cubierto por `.gitignore`).

## Estado
- [x] release.yml con job `publish` habilitado (commit previo a este guion).
- [x] Artifacts generados en `dist/`.
- [ ] Token provisto por el usuario.
- [ ] Publicación ejecutada y verificada.
