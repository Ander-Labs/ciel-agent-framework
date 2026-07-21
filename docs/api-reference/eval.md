# `ciel.eval` — Evaluación y testing reproducible (Fase 18)

Capa de evaluación **offline-safe por defecto**: las métricas propias son
deterministas y no requieren red ni extras. DeepEval/RAGAS/TruLens son
**opt-in** vía el extra `eval`; si no están instalados, `Evaluator` degrada a
métricas propias.

## Componentes

| Símbolo | Tipo | Descripción |
|---------|------|-------------|
| `EvalCase` | dataclass | Un caso: `query`, `expected`, `context`, `gold`, `metadata`. |
| `Evaluator` | clase | Corre un dataset sobre un agente/callable y acumula KPIs. |
| `Evaluator.run` / `arun` | método | Ejecuta (sync/async) y devuelve `List[EvalResult]`. |
| `Evaluator.kpis` | método | Agrega `pass_rate` y medias de cada métrica. |
| `Evaluator.export` | método | Exporta `results.json` (kpis + resultados). |
| `load_dataset` | función | Carga un dataset YAML de casos. |
| `exact_match`, `contains`, `f1_token` | métricas | Coincidencia cerrada. |
| `faithfulness`, `context_relevance` | métricas | RAG (tokens comunes respuesta↔contexto; usa `Retriever` si se pasa). |
| `answer_relevance` | métrica | Heurística de diagnóstico (no gating por defecto). |

## Uso mínimo

```python
import asyncio
from ciel.eval import Evaluator, load_dataset
from ciel.providers import MockProvider
from ciel.runtime import ChatRequest, ChatMessage

cases = load_dataset("tests/eval/smoke.yaml")

async def agent(query, **kw):
    p = MockProvider(mode="fixed", response="París")
    r = await p.complete(ChatRequest(messages=[ChatMessage(role="user", content=query)]))
    return r.choice.message.content

ev = Evaluator(agent=agent)
ev.run(cases, threshold=0.8)
print(ev.kpis())
ev.export("results.json")
```

## CLI

```bash
# Correr un dataset con MockProvider (offline)
ciel evaluate run --dataset tests/eval/smoke.yaml --provider mock --threshold 0.8

# Modo mapa explícito
ciel evaluate run --dataset ds.yaml --provider mock \
  --mock-map "capital de Francia=París,2+2=4"

# Regression gate contra un baseline
ciel evaluate regression --baseline results.json --dataset ds.yaml --provider mock

# Red-teaming (prompt injection / fuga de tenant) con MockProvider
ciel evaluate redteam --dataset adversarial.yaml --provider mock
```

El extra `eval` habilita métricas de terceros (se degradan a `None` si no
están instaladas):

```bash
pip install "mana-ciel[eval]"
```

::: ciel.eval
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true
