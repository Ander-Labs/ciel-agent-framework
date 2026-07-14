# Prompt nocturno — publicación GitHub + release (Fase 9 / v0.3.0)

> Guion autocontenido para ejecutar de noche. El paquete `mana-ciel` 0.3.0 YA
> está publicado en PyPI. Lo que falta es subir el tag + master a GitHub y
> crear el GitHub Release con las notas del CHANGELOG.

## Estado actual (verificado 2026-07-14)
- PyPI: `mana-ciel` 0.3.0 publicado (whl + sdist). OK.
- Local: commits `9b2846a` (cierre), `ab6c4fc` (docs DX), `936a0a8` (publicado
  en PyPI). Tag `v0.3.0` creado localmente, NO en origin.
- Origin solo tiene hasta `v0.2.0`. `gh` NO instalado en esta máquina.
- Suite: `uv run pytest` → 230 passed, 2 skipped.
- Token PyPI en `.env.local` (gitignoreado). NO se necesita para este paso.

## Tareas a ejecutar de noche
1. Push de master + tag al remote:
   ```
   git push origin master
   git push origin v0.3.0
   ```
2. Crear GitHub Release v0.3.0 con las notas de `CHANGELOG.md` sección
   `[0.3.0]` (líneas 7+). opciones:
   - Si `gh` está disponible:
     ```
     gh release create v0.3.0 --title "v0.3.0 — Fase 9 (Extensibilidad)" \
       --notes-file <(sed -n '7,/^## \[0.2.0\]/p' CHANGELOG.md)
     ```
   - Si NO hay `gh`: crear el release manualmente en
     https://github.com/Ander-Labs/ciel-agent-framework/releases/new
     usando el tag `v0.3.0` y pegando la sección `[0.3.0]` del CHANGELOG.
3. Verificar:
   - `git ls-remote --tags origin` muestra `v0.3.0`.
   - El GitHub Release existe y el workflow `release.yml` (job `publish`
     habilitado) no se dispara de forma inesperada porque ya está publicado.
   - (Opcional) `uv run pytest` verde tras el push.

## Notas de seguridad
- El token PyPI vive en `.env.local` (gitignoreado por `.env.*`). Nunca
  commitearlo ni pegarlo en el chat.
- Si se debe volver a publicar a PyPI: usar `uv publish` invocando uv desde
  Python con el token inline (ver QUIRK en memoria), NO vía `$ENV` (da 403 en
  Windows/bash).

## Comando único sugerido (una vez confirmado gh)
```bash
git push origin master && git push origin v0.3.0 && \
gh release create v0.3.0 --title "v0.3.0 — Fase 9 (Extensibilidad)" \
  --notes "$(sed -n '7,/^## \[0.2.0\]/p' CHANGELOG.md)"
```
