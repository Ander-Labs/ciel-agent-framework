# Cookbook: Evaluación y testing con `ciel.eval` (Fase 18)

Este cookbook muestra cómo evaluar un agente de forma **reproducible y
offline-safe** (sin red ni API keys) usando `MockProvider` y `ciel.evaluate`,
y cómo activar métricas de terceros (DeepEval/RAGAS/TruLens) con el extra `eval`.

## 1. Evaluación mínima con MockProvider

`MockProvider` es un proveedor determinista (modos `fixed`/`echo`/`map`) que no
hace ninguna llamada de red. Lo usamos como evaluable del `Evaluator`.

```python
import asyncio
from ciel.eval import Evaluator, load_dataset, EvalCase
from ciel.providers import MockProvider
from ciel.runtime import ChatRequest, ChatMessage


async def agent(query, **kw):
    p = MockProvider(mode="fixed", response="París")
    r = await p.complete(ChatRequest(messages=[ChatMessage(role="user", content=query)]))
    return r.choice.message.content


cases = [
    EvalCase(query="¿Capital de Francia?", expected="París"),
    EvalCase(query="¿Capital de España?", expected="Madrid"),
]
ev = Evaluator(agent=agent)
results = ev.run(cases, threshold=0.8)
print(ev.kpis())          # pass_rate, medias de exact_match/contains/f1_token/...
ev.export("results.json") # kpis + resultados por caso
```

## 2. Dataset en YAML

Crea `tests/eval/mi_dataset.yaml`:

```yaml
- query: "¿Capital de Francia?"
  expected: "París"
  context: "Francia es un país europeo; su capital es París."
- query: "¿Cuánto es 2 + 2?"
  expected: "4"
```

Y carga con `load_dataset`:

```python
from ciel.eval import load_dataset
cases = load_dataset("tests/eval/mi_dataset.yaml")
```

## 3. CLI `ciel evaluate`

```bash
# Run (offline, MockProvider)
ciel evaluate run --dataset tests/eval/mi_dataset.yaml --provider mock --threshold 0.8

# Modo mapa explícito (sin escribir código)
ciel evaluate run --dataset tests/eval/mi_dataset.yaml --provider mock \
  --mock-map "¿Capital de Francia?=París,¿Cuánto es 2 + 2?=4"

# Regression gate: compara contra un baseline previo
ciel evaluate regression --baseline results.json --dataset tests/eval/mi_dataset.yaml --provider mock

# Red-teaming: prompt injection / fuga de tenant (offline)
ciel evaluate redteam --dataset tests/eval/adversarial.yaml --provider mock
```

`ciel evaluate run` imprime una tabla Rich de KPIs y usa exit-code 1 si el
`pass_rate` cae por debajo de `--threshold` (ideal para CI).

## 4. Métricas deterministas (sin extras)

`ciel.eval` incluye métricas propias offline:

- `exact_match`, `contains`, `f1_token`: coincidencia cerrada.
- `faithfulness`: proporción de tokens de la respuesta presentes en el `context`.
- `context_relevance`: superposición de tokens entre la query y el contexto (o
  los chunks recuperados por un `Retriever` de `ciel.rag` si se pasa).
- `answer_relevance`: heurística de diagnóstico (no gating por defecto).

## 5. Métricas de terceros (opt-in, extra `eval`)

Instala el extra para habilitar DeepEval/RAGAS/TruLens:

```bash
pip install "mana-ciel[eval]"
```

`Evaluator(agent=..., use_third_party=True)` delega a esas librerías cuando
están disponibles; si no, **degrada a métricas propias** (igual que
LiteLLM/RAG). Las funciones `deepeval_faithfulness`, `ragas_faithfulness` y
`trulens_context_relevance` devuelven `None` cuando el extra no está instalado,
así el caller decide sin romper.

## 6. CI sin coste de tokens

El job `eval` de `.github/workflows/ci.yml` corre `tests/eval` y el smoke CLI
con `MockProvider` — sin red, sin API keys, sin flaky tests (todo determinista).
