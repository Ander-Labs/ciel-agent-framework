# `ciel.runtime` — Runtime de agentes y tools

Núcleo del runtime: DTOs de chat (`ChatMessage`, `ChatChoice`, `ChatRequest`,
`ChatResponse`), contratos de provider/modelo (`ChatProvider`, `ModelProvider`),
tool loop y despacho de herramientas (`ToolProvider`, `DefaultToolDispatcher`),
resultados de ejecución (`ToolLoopResult`, `AgentRuntimeResult`, `AgentContext`)
y el runtime concreto con trazas (`DefaultAgentRuntime`, `AgentRuntime`).

::: ciel.runtime
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

::: ciel.runtime.tools
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.tools_builtins
    options:
      show_root_heading: false
      members: true

::: ciel.runtime.memory
    options:
      show_root_heading: false
      members: true
