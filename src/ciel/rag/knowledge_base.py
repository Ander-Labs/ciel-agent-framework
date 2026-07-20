"""KnowledgeBase y Retriever para RAG enterprise (Pilar C — Fase 17).

Offline-safe: el default usa ``InMemoryVectorStore`` + ``DeterministicEmbeddingProvider``
(sin red). ``KnowledgeBase`` indexa documentos/chunks por tenant; ``Retriever``
hace búsqueda híbrida (BM25 + vector, fusión RRF + rerank) y devuelve contexto
formateado para inyectar en el prompt. ``SemanticCache`` cachea respuestas por
similitud semántica del query (reduce coste/red en producción).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ciel.rag.chunking import Chunk, chunk_documents
from ciel.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    cosine_similarity,
)
from ciel.rag.hybrid import BM25Index, HybridHit, hybrid_search, rerank
from ciel.rag.loaders import Document, load_documents
from ciel.rag.vector_store import InMemoryVectorStore, VectorStore


@dataclass
class RetrievalResult:
    """Resultado de una recuperación RAG."""

    text: str
    score: float
    source: str = ""
    metadata: dict = field(default_factory=dict)


class KnowledgeBase:
    """Índice de conocimiento por tenant (offline-safe por defecto)."""

    def __init__(
        self,
        *,
        tenant_id: Optional[str] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_store: Optional[VectorStore] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self._embed = embedding_provider or DeterministicEmbeddingProvider()
        self._vstore = vector_store or InMemoryVectorStore()
        self._bm25 = BM25Index()
        self._chunks: Dict[str, Chunk] = {}
        self._chunk_order: List[str] = []

    def add_texts(
        self,
        texts: Sequence[str],
        *,
        tenant_id: Optional[str] = None,
        metadatas: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> List[str]:
        tenant = tenant_id if tenant_id is not None else self.tenant_id
        docs = [
            Document(text=t, source=f"text:{i}", metadata=(metadatas[i] if metadatas else {}))
            for i, t in enumerate(texts)
        ]
        return self.add_documents(docs, tenant_id=tenant)

    def add_documents(
        self, docs: Sequence[Document], *, tenant_id: Optional[str] = None
    ) -> List[str]:
        tenant = tenant_id if tenant_id is not None else self.tenant_id
        chunks = chunk_documents(docs)
        return self.add_chunks(chunks, tenant_id=tenant)

    def add_chunks(
        self, chunks: Sequence[Chunk], *, tenant_id: Optional[str] = None
    ) -> List[str]:
        tenant = tenant_id if tenant_id is not None else self.tenant_id
        if not chunks:
            return []
        texts = [c.text for c in chunks]
        vectors = self._embed.embed(texts)
        # ID único global por chunk (uuid4) para evitar colisiones entre
        # documentos distintos que comparten doc_id/chunk_index. El doc_id
        # original se preserva en metadata para trazabilidad en retrieve().
        ids = [f"{tenant or '__none__'}:{uuid.uuid4().hex}" for _ in chunks]
        payloads = [c.metadata for c in chunks]
        self._vstore.upsert(
            tenant_id=tenant, texts=texts, vectors=vectors, payloads=payloads, ids=ids
        )
        for c, rid in zip(chunks, ids):
            self._bm25.add(rid, c.text)
            self._chunks[rid] = c
            self._chunk_order.append(rid)
        return ids

    def retrieve(
        self,
        query: str,
        *,
        tenant_id: Optional[str] = None,
        top_k: int = 5,
        alpha: float = 0.5,
    ) -> List[RetrievalResult]:
        tenant = tenant_id if tenant_id is not None else self.tenant_id
        qvec = self._embed.embed_one(query)
        vhits = self._vstore.query(tenant_id=tenant, vector=qvec, top_k=top_k)
        hybrid_hits: List[HybridHit] = [
            HybridHit(
                id=h.id,
                text=h.text,
                vector=cosine_similarity(qvec, h.vector) if h.vector else 0.0,
                payload=h.payload,
            )
            for h in vhits
        ]
        merged = rerank(
            hybrid_search(
                query=query, bm25_index=self._bm25, vector_hits=hybrid_hits, top_k=top_k
            ),
            alpha=alpha,
        )
        out: List[RetrievalResult] = []
        for h in merged:
            chunk = self._chunks.get(h.id)
            out.append(
                RetrievalResult(
                    text=h.text,
                    score=h.score,
                    source=(chunk.doc_id if chunk else ""),
                    metadata=h.payload,
                )
            )
        return out


class Retriever:
    """Wrapper de alto nivel: recupera y formatea contexto para el prompt."""

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        top_k: int = 5,
        alpha: float = 0.5,
        max_context_chars: int = 4000,
    ) -> None:
        self.kb = kb
        self.top_k = top_k
        self.alpha = alpha
        self.max_context_chars = max_context_chars

    def context(
        self, query: str, *, tenant_id: Optional[str] = None, top_k: Optional[int] = None
    ) -> str:
        results = self.kb.retrieve(
            query, tenant_id=tenant_id, top_k=top_k or self.top_k, alpha=self.alpha
        )
        if not results:
            return ""
        parts: List[str] = []
        total = 0
        for i, r in enumerate(results, 1):
            block = f"[{i}] (fuente: {r.source or 'kb'})\n{r.text}"
            if total + len(block) > self.max_context_chars:
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts)

    def results(
        self, query: str, *, tenant_id: Optional[str] = None, top_k: Optional[int] = None
    ) -> List[RetrievalResult]:
        return self.kb.retrieve(
            query, tenant_id=tenant_id, top_k=top_k or self.top_k, alpha=self.alpha
        )


class SemanticCache:
    """Caché semántica: hit si un query previo es suficientemente similar.

    Offline (coseno sobre embeddings deterministas por defecto). Reduce
    llamadas a LLM/red en producción. TTL opcional.
    """

    def __init__(
        self,
        *,
        embedder: Optional[EmbeddingProvider] = None,
        threshold: float = 0.92,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        self._embed = embedder or DeterministicEmbeddingProvider()
        self._threshold = threshold
        self._ttl = ttl_seconds
        self._store: Dict[str, tuple] = {}

    def get(self, query: str) -> Optional[Any]:
        qvec = self._embed.embed_one(query)
        best_key: Optional[str] = None
        best_sim = -1.0
        for key, (vec, value, ts) in self._store.items():
            sim = cosine_similarity(qvec, vec)
            if sim > best_sim:
                best_sim = sim
                best_key = key
        if best_key is not None and best_sim >= self._threshold:
            vec, value, ts = self._store[best_key]
            if self._ttl is not None and (time.time() - ts) > self._ttl:
                del self._store[best_key]
                return None
            return value
        return None

    def put(self, query: str, value: Any) -> None:
        self._store[hashlib.sha256(query.encode()).hexdigest()] = (
            self._embed.embed_one(query),
            value,
            time.time(),
        )

    def clear(self) -> None:
        self._store.clear()


__all__ = ["KnowledgeBase", "Retriever", "SemanticCache", "RetrievalResult"]
