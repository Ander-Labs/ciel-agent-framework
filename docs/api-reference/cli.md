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
