# Auto-aprendizaje (Fase 19, v0.13)

Receta mínima **offline** (sin red ni API keys) que muestra las tres primitivas
de auto-aprendizaje de Ciel: prompt versionado, reflexión post-run e
introspección de estado cognitivo, más la CLI `ciel reflect`.

Todas las clases usan `MockProvider` (determinista) o un `DummyProvider` local.

## 1. Prompt versionado

```python
from ciel.runtime.state_backend import build_state_backend
from ciel.runtime.prompt_versioning import PromptRegistry

backend = build_state_backend()  # SQLite en dev / Postgres en prod (tenant-safe)
reg = PromptRegistry(backend)

# Crea la versión inicial 0.0.0
v0 = reg.create("asistente", "Eres un asistente útil.", tenant_id="t1")
print(v0.version)            # "0.0.0"

# Evoluciona a 0.1.0 (bump minor) con changelog trazable
v1 = reg.update(
    "asistente",
    "Eres un asistente útil y conciso.",
    tenant_id="t1",
    bump="minor",
    changelog="más conciso",
)
print(v1.version, v1.previous_version)  # "0.1.0" "0.0.0"

# Linaje
tree = reg.evolution_tree("asistente", tenant_id="t1")
print(tree["lineage"])    # ["0.0.0", "0.1.0"]
```

## 2. Reflexión post-run (learning-from-failure)

```python
from ciel.api import Agent
from ciel.providers import MockProvider
from ciel.runtime import ChatRequest, ChatMessage

# MockProvider fijo: simula un run que falla en un tool.
agent = Agent(
    provider=MockProvider(mode="fixed", response="ok"),
    tools=[],
    reflection=True,          # habilita self-reflection (offline-safe)
    tenant_id="t1",
)

resp = agent.run("haz algo", tenant_id="t1")
# Si un tool falló, `resp.reflection` trae la lección determinista.
print(getattr(resp, "reflection", None))
```

`AgentResponse.reflection` es una **property aditiva**: si no hay reflexión
instalada o el run no falló, es `None`. Las lecciones se persisten como memoria
episódica `role="lesson"` (multitenant, reutiliza F17).

## 3. Introspección / estado cognitivo

```python
from ciel.api import Agent
from ciel.providers import MockProvider

agent = Agent(
    provider=MockProvider(mode="fixed", response="listo"),
    tools=[],
    introspection=True,      # registra CognitiveSnapshot post-run
    tenant_id="t1",
)

agent.run("primera tarea", tenant_id="t1")
agent.run("segunda tarea", tenant_id="t1")

# Vuelca los últimos snapshots del agente.
report = agent.introspect()
for snap in report.snapshots:
    print(snap.active_prompt_version, snap.had_failure, snap.confidence)
```

Cada `CognitiveSnapshot` lleva: versión de prompt activa, turnos de memoria,
tool calls, si falló, confianza heurística (0.3 fallo / 0.8 con tools / 1.0
directo) y un `rationale`. El bloque `[Estado cognitivo]` se inyecta en el
system prompt de los runs siguientes para que el modelo sea consciente de su
estado.

## 4. CLI `ciel reflect`

```bash
# KPIs de auto-reflexión sobre un dataset (offline, MockProvider)
ciel reflect run --dataset tests/eval/smoke.yaml --provider mock --threshold 0.0

# Linaje de un prompt versionado
ciel reflect history --name asistente --tenant-id t1

# Estado cognitivo de una sesión
ciel reflect introspect --session <session-id> --tenant-id t1
```

Todas las operaciones son **offline-safe** (sin red ni API keys).
