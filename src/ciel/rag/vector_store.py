"""Stores vectoriales para memoria semántica / RAG (Pilar B — Fase 17).

Offline-safe: ``InMemoryVectorStore`` funciona sin dependencias (coseno en
memoria, aislado por tenant). ``ChromadbVectorStore`` importa ``chromadb`` de
forma diferida solo si el usuario elige el extra ``rag``.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ciel.rag.embeddings import EmbeddingProvider, cosine_similarity


@dataclass
class VectorRecord:
    id: str
    tenant_id: Optional[str]
    vector: List[float]
    payload: Dict[str, Any] = field(default_factory=dict)
    text: str = ""


class VectorStore(ABC):
    """Contrato de índice vectorial (aislado por tenant_id)."""

    @abstractmethod
    def upsert(
        self,
        *,
        tenant_id: Optional[str],
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Optional[Sequence[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
    ) -> List[str]: ...

    @abstractmethod
    def query(
        self,
        *,
        tenant_id: Optional[str],
        vector: Sequence[float],
        top_k: int = 5,
    ) -> List[VectorRecord]: ...


class InMemoryVectorStore(VectorStore):
    """Índice vectorial en memoria (offline, sin dependencias).

    Aísla por ``tenant_id``: ``query`` solo devuelve records del tenant pedido.
    """

    def __init__(self) -> None:
        self._records: List[VectorRecord] = []

    def upsert(
        self,
        *,
        tenant_id: Optional[str],
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Optional[Sequence[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
    ) -> List[str]:
        out: List[str] = []
        for i, text in enumerate(texts):
            rid = ids[i] if ids is not None else str(uuid.uuid4())
            payload = payloads[i] if payloads is not None else {}
            # Reemplazo si ya existe el id (idempotente).
            self._records = [r for r in self._records if r.id != rid]
            self._records.append(
                VectorRecord(
                    id=rid,
                    tenant_id=tenant_id,
                    vector=list(vectors[i]),
                    payload=payload,
                    text=text,
                )
            )
            out.append(rid)
        return out

    def query(
        self,
        *,
        tenant_id: Optional[str],
        vector: Sequence[float],
        top_k: int = 5,
    ) -> List[VectorRecord]:
        scored = [
            (cosine_similarity(vector, r.vector), r)
            for r in self._records
            if r.tenant_id == tenant_id
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]


class ChromadbVectorStore(VectorStore):
    """Wrapper sobre ChromaDB (extra ``rag``; import diferido).

    Persistencia en disco vía ``path``. El embedding lo hace el caller (pasamos
    vectores ya calculados). Aísla por tenant vía metadato en Chroma.
    """

    def __init__(
        self,
        *,
        collection: str = "ciel_rag",
        path: Optional[str] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> None:
        try:
            import chromadb  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "ChromadbVectorStore requiere el extra 'rag' (pip install 'mana-ciel[rag]')."
            ) from exc
        self._embedding_provider = embedding_provider
        client = (
            chromadb.PersistentClient(path=path)
            if path
            else chromadb.Client()
        )
        self._client = client
        self._collection = client.get_or_create_collection(collection)

    def upsert(
        self,
        *,
        tenant_id: Optional[str],
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Optional[Sequence[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
    ) -> List[str]:
        ids_out: List[str] = []
        for i, text in enumerate(texts):
            rid = ids[i] if ids is not None else str(uuid.uuid4())
            payload = dict(payloads[i]) if payloads is not None else {}
            metadata = {"tenant_id": tenant_id or "__none__", **payload}
            self._collection.upsert(
                ids=[rid],
                embeddings=[list(vectors[i])],
                documents=[text],
                metadatas=[metadata],
            )
            ids_out.append(rid)
        return ids_out

    def query(
        self,
        *,
        tenant_id: Optional[str],
        vector: Sequence[float],
        top_k: int = 5,
    ) -> List[VectorRecord]:
        res = self._collection.query(
            query_embeddings=[list(vector)],
            n_results=top_k,
            where={"tenant_id": tenant_id or "__none__"},
        )
        out: List[VectorRecord] = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        for i, rid in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            out.append(
                VectorRecord(
                    id=rid,
                    tenant_id=meta.get("tenant_id"),
                    vector=[],
                    payload={k: v for k, v in meta.items() if k != "tenant_id"},
                    text=docs[i] if i < len(docs) else "",
                )
            )
        return out


__all__ = ["VectorRecord", "VectorStore", "InMemoryVectorStore", "ChromadbVectorStore"]
