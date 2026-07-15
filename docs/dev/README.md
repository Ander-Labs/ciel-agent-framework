# docs/dev — Diario de ingeniería INTERNO

> [!WARNING]
> **Diario de ingeniería INTERNO. No es documentación oficial del producto.**
>
> El contenido de `docs/dev/` es el registro de trabajo del agente de
> desarrollo (prompts de orquestación, progreso por fase, diseños técnicos y
> notas de sesión). **NO se publica en el sitio web** (MkDocs Material) y no
> forma parte de la DX pública. Los usuarios deben consultar `docs/guide/`,
> `docs/roadmap.md`, `docs/upgrade.md`, `docs/runbooks/`, `docs/design/` y
> `docs/sdk/` para documentación de uso.

## Qué hay aquí

- **`INDEX.md`** — Índice de desarrollo: estado por fase y comandos de
  verificación (mantenido por el agente de desarrollo).
- **`FASE0_PROGRESS.md` … `FASE9_PROGRESS.md`** — Progreso y cierre de cada
  fase (qué se entregó, bugs de raíz corregidos, pendiente).
- **`FASE5_DESIGN.md` … `FASE9_DESIGN.md`** — Diseño *best-of-breed* de los
  módulos de cada fase.
- **`FASE3_RESUME.md`** — Reanudación / pendientes de Fase 3.
- **`NOCTURNO_PROMPT.md`** — Prompt de orquestación nocturna del agente.
- **`PUBLISH_PYPI_PROMPT_v0.3.0.md`** — Prompt de publicación en PyPI v0.3.0.
- **`PENDIENTES.md`** — *Gap analysis* de las Fases 7/8 (lo que falta por terminar).
- **`CIERRE_SESION.md`** — Cierre de sesión con subagentes (board SQLite, SSE, +5 tests).

## Estado actual (resumen)

- Fases 0–9: **CERRADAS**.
  - Fase 8: Deploy HA + observabilidad + madurez (Helm HA, OTel centralizado,
    adapters Teams/Discord/WebUI, HIL en grafo, runbooks, release v0.2.0).
  - Fase 9: Extensibilidad — plugin system, providers reales, tools de fábrica,
    DX; publicada en PyPI como `mana-ciel==0.3.0`.
- Suite verificada: **230 passed, 2 skipped**.

## Dónde encontrar la documentación pública

| Tema | Ruta |
|------|------|
| Guía de uso (DX) | `docs/guide/` |
| Roadmap para usuarios | `docs/roadmap.md` |
| Guía de migración | `docs/upgrade.md` |
| Runbooks operativos | `docs/runbooks/` (deploy, incident, rollback, backup, hpa) |
| Diseño de multitenancy | `docs/design/multi_tenancy.md` |
| SDK público | `docs/sdk/README.md` |
