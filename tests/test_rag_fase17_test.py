"""Tests offline de RAG / memoria semántica (Pilares B/C — Fase 17, v0.11.0).

Usa únicamente implementaciones offline (InMemoryVectorStore,
DeterministicEmbeddingProvider, BM25, semantic cache). Sin red, sin chromadb,
sin OpenAI. Verifica KB/Retriever, hybrid search, rerank, semantic cache y
aislamiento por tenant.
"""

from __future__ import annotations

from ciel.rag import (
    DeterministicEmbeddingProvider,
    InMemoryVectorStore,
    KnowledgeBase,
    Retriever,
    SemanticCache,
)
from ciel.rag.chunking import chunk_document
from ciel.rag.embeddings import cosine_similarity
from ciel.rag.hybrid import BM25Index, hybrid_search, rerank
from ciel.rag.loaders import Document
from ciel.rag.tools import make_kb_add_tool, make_retrieve_tool, rag_tools
from ciel.runtime.tools import ToolResult


def _kb() -> KnowledgeBase:
    kb = KnowledgeBase(tenant_id="t1")
    kb.add_texts(
        [
            "Ciel Agent Framework soporta multi-tenancy nativo con aislamiento por tenant_id.",
            "El gateway expone endpoints de salud /healthz y /readyz.",
            "La fase 17 añade memoria episódica y RAG enterprise.",
            "Los providers soportan LiteLLM para 100+ modelos.",
        ]
    )
    return kb


def test_knowledge_base_retrieve_returns_relevant():
    kb = _kb()
    results = kb.retrieve("multi-tenancy nativo", tenant_id="t1", top_k=2)
    assert len(results) >= 1
    assert any("multi-tenancy" in r.text for r in results)


def test_retriever_context_formats():
    retriever = Retriever(_kb(), top_k=2)
    ctx = retriever.context("health endpoints", tenant_id="t1")
    assert "healthz" in ctx or "readyz" in ctx


def test_tenant_isolation_in_vector_store():
    store = InMemoryVectorStore()
    emb = DeterministicEmbeddingProvider()
    v1 = emb.embed_one("secreto del tenant uno")
    v2 = emb.embed_one("secreto del tenant dos")
    store.upsert(tenant_id="t1", texts=["secreto del tenant uno"], vectors=[v1], ids=["a"])
    store.upsert(tenant_id="t2", texts=["secreto del tenant dos"], vectors=[v2], ids=["b"])
    hits_t1 = store.query(tenant_id="t1", vector=v1, top_k=5)
    assert [h.id for h in hits_t1] == ["a"]


def test_hybrid_search_fuses_bm25_and_vector():
    bm25 = BM25Index()
    emb = DeterministicEmbeddingProvider()
    doc_id = "d1"
    text = "memoria episódica del agente por tenant"
    bm25.add(doc_id, text)
    vec = emb.embed_one("memoria episódica")
    vhits = [
        type("_H", (), {"id": doc_id, "text": text, "vector": cosine_similarity(vec, vec), "payload": {}})()
    ]
    merged = rerank(
        hybrid_search(query="memoria episódica", bm25_index=bm25, vector_hits=vhits, top_k=3)
    )
    assert merged[0].id == doc_id


def test_semantic_cache_hit_and_miss():
    cache = SemanticCache(threshold=0.80)
    assert cache.get("¿qué es Ciel?") is None  # miss (vacío)
    cache.put("qué es ciel", "Ciel es un framework de agentes")
    # Misma consulta EXACTA => hit determinista (similitud = 1.0).
    got = cache.get("qué es ciel")
    assert got == "Ciel es un framework de agentes"
    # Consulta muy distinta => miss.
    assert cache.get("precio del café en Madrid") is None


def test_chunking_paragraph_and_token():
    doc = Document(
        text="Párrafo uno.\n\nPárrafo dos sobre RAG.\n\nPárrafo tres sobre memoria.",
        source="doc.md",
    )
    paras = chunk_document(doc, strategy="paragraph")
    assert len(paras) >= 1
    tokens = chunk_document(doc, strategy="token", chunk_size=4, overlap=1)
    assert len(tokens) >= 1


def test_rag_tools_wrap_kb():
    kb = _kb()
    tools = rag_tools(kb, top_k=2)
    assert len(tools) == 2
    retrieve = tools[0]
    # Contrato del dispatcher: callable_(arguments, *, tool_call_id, tenant_id).
    res: ToolResult = retrieve.callable_(  # type: ignore[attr-defined]
        {"query": "RAG enterprise"}, tool_call_id="c1", tenant_id="t1"
    )
    assert isinstance(res, ToolResult)
    assert res.error is None
    assert "RAG" in res.output

    add_tool = tools[1]
    before = len(kb._chunks)
    added: ToolResult = add_tool.callable_(  # type: ignore[attr-defined]
        {"text": "nuevo hecho indexado en la KB"}, tool_call_id="c2", tenant_id="t1"
    )
    assert added.error is None
    after = len(kb._chunks)
    assert after > before


def test_make_retrieve_tool_explicit():
    kb = _kb()
    tool = make_retrieve_tool(kb, name="buscar")
    assert tool.spec.name == "buscar"
    kb_add = make_kb_add_tool(kb, name="agregar")
    assert kb_add.spec.name == "agregar"
