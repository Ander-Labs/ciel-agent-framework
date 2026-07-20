# Cookbook: Memoria episódica y RAG (Fase 17 / v0.11.0)

Este cookbook muestra cómo añadir memoria conversacional y RAG a un agente
Ciel, **sin red ni API keys** (los embeddings/deterministas funcionan offline).

## 1. Memoria episódica

La memoria episódica persiste los turnos `(user, assistant)` por
`(tenant_id, session_id)` y los re-inyecta como contexto en el system prompt.

```python
from ciel import Agent, EpisodicStore, MemoryConfig, EchoProvider

# Backend por defecto: SQLite en disco (offline-safe).
store = EpisodicStore()  # o EpisodicStore(SqliteStateBackend("ciel.sqlite"))

agent = Agent(
    provider=EchoProvider(),          # cámbialo por OpenAIProvider(...) en prod
    model="echo",
    memory=store,
    memory_config=MemoryConfig(recent_turns=8),
)

# Primer turno: la memoria está vacía.
r1 = agent.run("soy Ana", tenant_id="acme")
# Segundo turno: "soy Ana" se recupera e inyecta como contexto.
r2 = agent.run("qué nombre dije", tenant_id="acme")
assert "Ana" in r2.text
```

La memoria está **aislada por tenant**: `store.search(tenant_id="acme", query=...)`
nunca devuelve episodios de otro tenant.

## 2. RAG enterprise (offline-safe)

`ciel.rag` incluye un índice vectorial en memoria con embeddings
deterministas (sin red) y búsqueda híbrida BM25 + vector con fusión RRF.

```python
from ciel.rag import KnowledgeBase, Retriever, rag_tools

kb = KnowledgeBase(tenant_id="acme")
kb.add_texts([
    "Ciel soporta multi-tenancy nativo con aislamiento por tenant_id.",
    "El gateway expone /healthz y /readyz para k8s.",
    "La Fase 17 añade memoria episódica y RAG enterprise.",
])

retriever = Retriever(kb)
hits = retriever.retrieve("¿qué es el multi-tenancy?", tenant_id="acme", top_k=3)
for h in hits:
    print(h.score, h.chunk.text)
```

### 2.1 Enchufar RAG como tools del agente

```python
from ciel import Agent
from ciel.rag import KnowledgeBase, rag_tools

kb = KnowledgeBase(tenant_id="acme")
kb.add_texts(["Ciel Agent Framework es un framework de agentes autónomos."])

agent = Agent(provider=EchoProvider(), model="echo")
agent.tools += rag_tools(kb)   # añade retrieve + kb_add
```

Las tools respetan el contrato del dispatcher: `callable_(arguments, *,
tool_call_id, tenant_id)`.

## 3. Caché semántico

```python
from ciel.rag import SemanticCache

cache = SemanticCache(threshold=0.80)
assert cache.get("hola") is None
cache.put("hola", "¡Hola! ¿en qué ayudo?")
assert cache.get("hola") == "¡Hola! ¿en qué ayudo?"
```

## 4. Requisitos

- El paquete base corre sin extras. Para persistencia vectorial en disco o
  carga de PDF instala el extra `rag`:

  ```bash
  pip install mana-ciel[rag]
  ```

- Toda la memoria y el RAG son **offline-safe** por defecto (sin red, sin
  keys). Los embeddings deterministas garantizan resultados reproducibles en
  CI.
