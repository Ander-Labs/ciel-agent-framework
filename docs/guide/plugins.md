# Plugins (extensibilidad sin tocar el core) — preview v0.3.0

> **Estado: preview.** El registry de plugins (`ciel.plugins`) ya está
> implementado y registra los builtins (OpenAI/Anthropic/Gemini + toolset
> `builtins`). El descubrimiento automático por *entry points* de terceros se
> activa al instalar paquetes que los declaren.

## Qué es

Un plugin es un paquete Python que aporta **providers**, **tools** o **agents**
al framework sin que tengas que editar el código de Ciel. Se declaran vía
*entry points* de `importlib.metadata`:

| Grupo de entry point | Qué registra        |
|----------------------|---------------------|
| `ciel.providers`     | providers (LLMs)    |
| `ciel.tools`         | toolsets/herramientas |
| `ciel.agents`        | agentes             |

## Cómo crear un plugin

`pyproject.toml` de tu paquete:

```toml
[project.entry-points."ciel.plugins"]
mi_provider = "mi_paquete.plugins:register_provider"
mis_tools   = "mi_paquete.plugins:register_tools"
```

Y en `mi_paquete/plugins.py`:

```python
from ciel.plugins import default_registry
from ciel.providers import ChatProvider

def register_provider():
    reg = default_registry()
    reg.register_provider("mi-provider", MiProvider())

def register_tools():
    reg = default_registry()
    # registrar toolsets vía reg.tools (ToolRegistry)
    ...
```

## Cómo se consume

Solo instalas el paquete:

```bash
pip install mi-plugin-ciel
```

Al arrancar, `default_registry()` descubre e importa los entry points
automáticamente. Tu provider/tool aparece en el registry sin import manual.

## Por qué importa

Es lo que convierte a Ciel de "tu código" en un **framework**: la comunidad puede
publicar integraciones (nuevos LLMs, tools de nube, conectores) y tú las activas
con `pip install`. El core no cambia.
