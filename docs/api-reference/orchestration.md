# `ciel.orchestration` — Orquestación

Primitivas de orquestación best-of-breed montadas sobre el Supervisor:

* **Grafo de estado explícito** (estilo LangGraph) con checkpoint:
  `StateGraph`, `GraphNode`, `GraphEdge`, `GraphRunner`, `GraphState` y stores.
* **Flows event-driven** (estilo CrewAI): `Flow`, `FlowRunner`, `FlowStep`.
* **Group chat** (estilo AutoGen): `GroupChat`, `GroupChatManager`, `Agent`.
* **Root agent con sub-agents** (estilo ADK): `RootAgent`, `Specialist`.
* **Agencia autónoma en bucle** (Fase 6): `AutonomousAgent`, `EventLoop`, `Task`.
* **Sesiones**: `SessionStore`.

::: ciel.orchestration
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.orchestration.graph
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.flows
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.chat
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.root
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.agent
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.session
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.board
    options:
      show_root_heading: false
      members: true

::: ciel.orchestration.supervisor
    options:
      show_root_heading: false
      members: true
