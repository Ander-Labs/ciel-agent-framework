# `ciel.adapters` — Adapters de mensajería

Adapters de mensajería agnósticos al canal (Fase 8). Extienden el contrato de
`ciel.gateway.adapter` (`MessagingAdapter` / `Message`) con implementaciones
concretas para Microsoft Teams, Discord y Web UI, más un `FakeAdapter`
totalmente offline usado por los tests. Todos los adapters son
*runtime-agnostic*.

::: ciel.adapters
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true
