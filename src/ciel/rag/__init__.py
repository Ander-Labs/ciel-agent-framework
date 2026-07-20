"""RAG y memoria semántica (Pilar B/C — Fase 17, v0.11.0).

Este paquete es **offline-safe por defecto**: ningún import de red/vector se
realiza al importar ``ciel``. Los backends pesados (chromadb, OpenAI) se
importan de forma diferida SOLO cuando el usuario los elige explícitamente.

Superficie pública:
* ``ciel.rag.embeddings`` — ``EmbeddingProvider`` + impls (determinista offline, OpenAI opt-in).
* ``ciel.rag.vector_store`` — ``VectorStore`` + ``InMemoryVectorStore`` (offline) / ``ChromadbVectorStore`` (lazy).
* ``ciel.rag.hybrid`` — ``hybrid_search`` (BM25 + vector, fusión RRF) y ``rerank``.
* ``ciel.rag.loaders`` — cargadores de documentos (MD/HTML/TXT offline; PDF opt-in).
* ``ciel.rag.chunking`` — estrategias de chunking.
* ``ciel.rag.knowledge_base`` — ``KnowledgeBase`` / ``Retriever`` de alto nivel.
"""

from ciel.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from ciel.rag.vector_store import (
    ChromadbVectorStore,
    InMemoryVectorStore,
    VectorStore,
)
from ciel.rag.loaders import Document, load_document, load_documents
from ciel.rag.chunking import Chunk, chunk_document, chunk_documents
from ciel.rag.knowledge_base import (
    KnowledgeBase,
    RetrievalResult,
    Retriever,
    SemanticCache,
)
from ciel.rag.tools import make_kb_add_tool, make_retrieve_tool, rag_tools

__all__ = [
    "EmbeddingProvider",
    "DeterministicEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "VectorStore",
    "InMemoryVectorStore",
    "ChromadbVectorStore",
    "Document",
    "load_document",
    "load_documents",
    "Chunk",
    "chunk_document",
    "chunk_documents",
    "KnowledgeBase",
    "Retriever",
    "RetrievalResult",
    "SemanticCache",
    "make_retrieve_tool",
    "make_kb_add_tool",
    "rag_tools",
]
