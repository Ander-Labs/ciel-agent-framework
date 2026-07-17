# Skill Library (Autonomía I — Fase 12)

La **Skill Library** es el primer nivel de autonomía de Ciel: permite que un
agente **cree, verifique, versione, componga y enseñe** skills (trozos de código
Python ejecutables) sin intervención humana. Todo el subsistema es
**offline-safe**: no requiere red ni API keys, y los skills se verifican con
casos de prueba ejecutables antes de ser usados.

Módulos involucrados (todos bajo `ciel.runtime`):

| Módulo | Responsabilidad |
|---|---|
| `skills_lib` | `SkillLibrary` (store escribible) + `SkillVerifier` (auto-verificación). |
| `skill_versioning` | Changelog por versión + `evolution_tree` (Skill Evolution Tree). |
| `skill_composition` | `SkillComposition` fusiona N skills (`sequence`/`parallel`/`selector`). |
| `skill_doc` | `generate_doc` / `to_markdown` (doc desde AST). |
| `skill_agent_integration` | `@ciel.skill`, `Agent(skills=[...])`, `agent.teach(...)`. |
| `skill_metrics` | `SkillMetrics` por tenant (uso, éxito, latencia). |

> El low-level `ciel.runtime.skills` (`Skill` / `SkillRegistry`) **no cambia**:
> la librería es una fachada escribible encima de él, por compatibilidad hacia
> atrás.

---

## 1. SkillLibrary — store dinámico

`SkillLibrary` envuelve un `SkillRegistry` y añade creación/registro/actualización
en memoria, con aislamiento opcional por `tenant_id`.

```python
from ciel.runtime.skills_lib import SkillLibrary

lib = SkillLibrary()

# Crear un skill desde código fuente (valida sintaxis con compile()).
lib.create_from_code(
    name="add",
    description="Suma dos enteros",
    code="def add(a, b):\n    return a + b\n",
)

skill = lib.get("add")
print(skill.name, skill.sha256[:12])     # add  <hash[:12]>

# Listar (última versión de cada nombre); se puede filtrar por category/tenant.
for s in lib.list_skills():
    print(s.name, s.category)

# Actualizar con bump semántico (major/minor/patch) preservando history().
lib.update(name="add", code="def add(a, b):\n    return int(a) + int(b)\n", bump="patch")
print([v.sha256[:8] for v in lib.history("add")])   # todas las versiones
```

API pública de `SkillLibrary`:

- `create_from_code(*, name, description, code, category=None, tenant_id=None, metadata=None) -> Skill`
  — compila el código; lanza `SkillError` si no compila. **No ejecuta** el código.
- `register(skill) -> Skill` — registra un `Skill` ya construido.
- `get(name) -> Optional[Skill]` — última versión (cae al registry de disco si no está en memoria).
- `list_skills(*, category=None, tenant_id=None) -> List[Skill]` — últimas versiones.
- `history(name) -> List[Skill]` — todas las versiones, antigua → nueva.
- `update(*, name, description=None, code=None, category=None, bump="patch") -> Skill` — nueva versión.
- `remove(name) -> bool` — elimina de memoria.
- `load_from_disk() -> List[Skill]` — descubre skills del registry y los indexa.

---

## 2. SkillVerifier — auto-verificación offline

Un skill no se fía a ciegas: `SkillVerifier` valida la sintaxis y ejecuta casos
de prueba antes de usarlo.

```python
from ciel.runtime.skills_lib import SkillLibrary, SkillVerifier

lib = SkillLibrary()
lib.create_from_code(name="add", description="suma", code="def add(a, b):\n    return a + b\n")

verifier = SkillVerifier(library=lib)
result = verifier.verify_by_name("add", test_cases=[
    {"call": {"a": 2, "b": 3}, "expect": 5},
    {"call": {"a": 0, "b": 0}, "expect": 0},
])
print(result.passed, result.attempts)   # True 2
```

`SkillVerificationResult` expone: `passed: bool`, `skill: str`, `attempts: int`,
y en fallo `error` / `traceback` / `expected` / `got`.

`SkillVerifier.verify(skill, *, test_cases)` (o `verify_by_name(name, ...)`):
1. Validación de sintaxis (`compile`).
2. `exec` del código en un namespace aislado.
3. Resuelve la callable (la nombrada como el skill, o la primera callable).
4. Por cada caso invoca `fn(**call)` y compara con `expect`.

> `exec` aquí es deliberado y **offline-safe**: el contenido es de
> confianza-por-construcción (lo escribió el agente o el desarrollador en el
> mismo proceso), no proviene de la red.

---

## 3. Versioning + changelog (evolution tree)

`skill_versioning` añade metadatos de versión semanticos **sin tocar** el
`Skill`/`SkillRegistry` subyacente: lee `history(name)` y escribe en
`metadata`.

```python
from ciel.runtime.skills_lib import SkillLibrary
from ciel.runtime.skill_versioning import set_changelog, changelog, evolution_tree

lib = SkillLibrary()
lib.create_from_code(name="add", description="suma", code="def add(a, b):\n    return a + b\n")
lib.update(name="add", code="def add(a, b):\n    return int(a) + int(b)\n", bump="patch")

set_changelog(lib, "add", "0.0.1", "Convierte args a int antes de sumar.")
print(changelog(lib, "add"))            # {'0.0.0': '', '0.0.1': 'Convierte args a int...'}

tree = evolution_tree(lib, "add")
print(tree["root"], tree["lineage"])    # versión base y linaje ordenado
print(tree["nodes"]["0.0.1"]["parent"]) # versión padre
```

- `SkillVersion.parse("1.2.0")` / `.bump("minor")` — utilidades semánticas.
- `set_changelog(lib, name, version, text)` — adjunta changelog + `released_at`.
- `changelog(lib, name) -> {version: text}`.
- `evolution_tree(lib, name) -> {name, root, lineage, nodes}` — semilla del
  **Skill Evolution Tree**: cada nodo tiene `parent`, `children`, `sha256`,
  `changelog` y `released_at`.

---

## 4. Composition engine

`SkillComposition.compose` fusiona N skills en uno nuevo, cableando sus callables
según un combinator:

- `sequence` — alimenta la salida de uno a la entrada del siguiente (pipeline).
- `parallel` — invoca a todos con los mismos args y devuelve la lista de resultados.
- `selector` — prueba uno a uno y devuelve el primer resultado que no falle.

```python
from ciel.runtime.skills import Skill
from ciel.runtime.skill_composition import SkillComposition

s1 = Skill(name="inc", description="", content="def inc(x):\n    return x + 1\n")
s2 = Skill(name="dbl", description="", content="def dbl(x):\n    return x * 2\n")

composed = SkillComposition().compose("inc_then_dbl", [s1, s2], "sequence")
print(composed.metadata["composition"])   # {'combinator': 'sequence', 'source_skills': ['inc', 'dbl'], ...}

# Ejecutable de forma aislada:
ns = {}
exec(composed.content, ns)
print(ns["inc_then_dbl"](3))   # (3+1)*2 = 8
```

`compose(name, skills, combinator, *, library=None, description=None, category=None)`
devuelve el `Skill` compuesto y, si se pasa `library`, lo registra en ella.

---

## 5. Doc auto-generation

`skill_doc` genera documentación desde el código fuente con `ast` (sin ejecutar):

```python
from ciel.runtime.skills import Skill
from ciel.runtime.skill_doc import generate_doc, to_markdown

skill = Skill(name="add", category="math", content='def add(a, b):\n    "Suma dos enteros."\n    return a + b\n')

print(generate_doc(skill))   # {'name': 'add', 'description': 'Suma dos enteros.', 'category': 'math'}
print(to_markdown(skill))    # frontmatter YAML + cuerpo markdown
```

- `generate_doc(skill) -> {"name", "description", "category"}` — toma nombre y
  docstring de la **primera** callable.
- `to_markdown(skill) -> str` — documento markdown con frontmatter `name` /
  `description` / `category` y la firma de la función.

---

## 6. Integración con `ciel.Agent`

`skill_agent_integration` conecta la librería con la fachada de alto nivel
(`ciel.Agent`) **sin romper la API existente**. Se inyecta automáticamente al
importar `ciel` (vía `install_agent_skill_support` en `ciel/api.py`).

### `@ciel.skill` — declarar un skill

```python
import ciel

@ciel.skill
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

# Disponible de inmediato en la librería singleton:
ciel.global_skill_library.get("add")
```

El decorador valida la sintaxis en tiempo de definición y registra la función
(como `Skill`) en `global_skill_library`, guardando la callable original en
`metadata["_callable"]`.

### `Agent(skills=[...])` — cargar skills al construir

```python
import ciel

@ciel.skill
def add(a: int, b: int) -> int:
    "Suma dos enteros."
    return a + b

agent = ciel.Agent(provider=mi_provider, skills=["add"])
resp = agent.run("¿Cuánto es 2 + 3?", tenant_id="acme")
```

### `agent.teach(skill)` / `ciel.teach(agent, skill)` — enseñar en runtime

Convierte un `Skill` en una tool ejecutable y la registra en el agente. Si pasas
`test_cases` y `verify=True` (por defecto), el skill pasa primero por
`SkillVerifier`; si no pasa, lanza `SkillVerificationError`.

```python
from ciel.runtime.skills_lib import SkillLibrary
import ciel

lib = SkillLibrary()
skill = lib.create_from_code(
    name="mul", description="multiplica", code="def mul(a, b):\n    return a * b\n",
)

agent = ciel.Agent(provider=mi_provider)
ciel.teach(agent, skill, test_cases=[{"call": {"a": 2, "b": 3}, "expect": 6}])
# o: agent.teach(skill, test_cases=[...])
```

- `ciel.teach(agent, skill, *, test_cases=None, verify=True)` — versión función.
- `agent.teach(skill, ...)` — método de instancia enlazado.
- `agent.load_skills(["nombre1", "nombre2"])` — carga varios desde la librería global.
- `global_skill_library` — la instancia singleton compartida por el proceso.

---

## 7. Skill metrics por tenant

`SkillMetrics` registra métricas de uso en memoria, aisladas por `tenant_id`:

```python
from ciel.runtime.skill_metrics import SkillMetrics

metrics = SkillMetrics()
metrics.record_usage("lib", "add", success=True, latency_ms=12.5, tenant_id="acme")
print(metrics.metrics("add", tenant_id="acme"))
# {'calls': 1, 'successes': 1, 'failures': 0, 'success_rate': 1.0, 'avg_latency_ms': 12.5}

metrics.reset(tenant_id="acme")   # limpia el namespace de ese tenant
```

- `record_usage(lib, name, success, latency_ms=0.0, *, tenant_id=None)`.
- `metrics(name, tenant_id=None) -> {calls, successes, failures, success_rate, avg_latency_ms}`
  (skills desconocidos devuelven contadores a cero, no lanzan).
- `reset(*, tenant_id=None)` — limpia el namespace indicado (o el global).

---

## CLI: `ciel skills`

Consulta [`docs/api-reference/cli.md`](../api-reference/cli.md#ciel-skills--gestin-de-la-skill-library-offline)
para la referencia completa del subcomando `ciel skills` (`list`, `create`,
`verify`, `remove`), operativo de forma offline.
