"""Búsqueda híbrida y re-ranking (Pilar B/C — Fase 17).

Combina BM25 (sobre el corpus indexado) + similitud vectorial con fusión
**RRF** (Reciprocal Rank Fusion) y un re-rank opcional. Todo offline-safe:
el default no requiere red. BM25 se implementa como índice ligero in-memory
sobre los chunks del ``KnowledgeBase``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple


@dataclass

class HybridHit:
    id: str
    text: str
    score: float = 0.0
    bm25: float = 0.0
    vector: float = 0.0
    payload: dict = field(default_factory=dict)


def _tokenize(text: str) -> List[str]:
    return [t for t in text.lower().split() if t]


class BM25Index:
    """BM25 in-memory ligero (offline). Indexa documentos por id."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: Dict[str, List[str]] = {}
        self._df: Dict[str, int] = defaultdict(int)
        self._avgdl: float = 0.0
        self._n: int = 0

    def add(self, doc_id: str, text: str) -> None:
        if doc_id in self._docs:
            self._remove(doc_id)
        tokens = _tokenize(text)
        self._docs[doc_id] = tokens
        for term in set(tokens):
            self._df[term] += 1
        if tokens:
            self._avgdl = (self._avgdl * self._n + len(tokens)) / (self._n + 1)
        self._n += 1

    def _remove(self, doc_id: str) -> None:
        tokens = self._docs.pop(doc_id, [])
        for term in set(tokens):
            self._df[term] = max(0, self._df[term] - 1)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        if self._n == 0:
            return []
        q_terms = _tokenize(query)
        scores: Dict[str, float] = defaultdict(float)
        for term in q_terms:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
            for doc_id, tokens in self._docs.items():
                f = tokens.count(term)
                if f == 0:
                    continue
                denom = f * (self._k1 + 1) / (
                    f + self._k1 * (1 - self._b + self._b * len(tokens) / (self._avgdl or 1.0))
                )
                scores[doc_id] += idf * denom
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def hybrid_search(
    *,
    query: str,
    bm25_index: BM25Index,
    vector_hits: Sequence[HybridHit],
    top_k: int = 5,
    rrf_k: int = 60,
) -> List[HybridHit]:
    """Fusión RRF de BM25 + vector. ``vector_hits`` trae los top por coseno."""
    # Rank de BM25.
    bm25_ranked = bm25_index.search(query, top_k=max(top_k, len(vector_hits)))
    rrf: Dict[str, HybridHit] = {}

    def _ensure(hid: str, text: str, payload: dict) -> HybridHit:
        if hid not in rrf:
            rrf[hid] = HybridHit(id=hid, text=text, payload=payload)
        else:
            # Preserva text/payload ya conocidos de vector_hits.
            if not rrf[hid].text and text:
                rrf[hid].text = text
            if not rrf[hid].payload and payload:
                rrf[hid].payload = payload
        return rrf[hid]

    for rank, (hid, score) in enumerate(bm25_ranked):
        hit = _ensure(hid, "", {})
        hit.bm25 = score
        hit.score += 1.0 / (rrf_k + rank + 1)

    for rank, v in enumerate(vector_hits):
        hit = _ensure(v.id, v.text, v.payload)
        hit.vector = v.vector
        hit.score += 1.0 / (rrf_k + rank + 1)

    merged = sorted(rrf.values(), key=lambda h: h.score, reverse=True)
    return merged[:top_k]


def rerank(hits: Sequence[HybridHit], *, alpha: float = 0.5) -> List[HybridHit]:
    """Re-rank combinando BM25 y vector con peso ``alpha`` (offline).

    ``alpha`` = peso del score vectorial (0= solo BM25, 1= solo vector).
    Por defecto equilibrado. Un cross-encoder real puede sustituir esto.
    """
    norm_bm25 = _max_or_one([h.bm25 for h in hits])
    norm_vec = _max_or_one([h.vector for h in hits])
    for h in hits:
        combined = (1 - alpha) * (h.bm25 / norm_bm25) + alpha * (h.vector / norm_vec)
        # Mezcla con el score RRF ya acumulado para estabilidad.
        h.score = 0.5 * h.score + 0.5 * combined
    return sorted(hits, key=lambda h: h.score, reverse=True)


def _max_or_one(xs: Sequence[float]) -> float:
    m = max(xs) if xs else 0.0
    return m if m > 0 else 1.0


__all__ = ["HybridHit", "BM25Index", "hybrid_search", "rerank"]
