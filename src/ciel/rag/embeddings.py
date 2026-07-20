"""Embeddings para memoria semántica / RAG (Pilar B — Fase 17).

Offline-safe: el default es ``DeterministicEmbeddingProvider`` (hash-based,
sin red ni API keys) para que los tests y el dev funcionen sin dependencias.
``OpenAIEmbeddingProvider`` se importa de forma diferida y requiere API key.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence


class EmbeddingProvider(ABC):
    """Contrato mínimo de embeddings."""

    dim: int = 256

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> List[List[float]]: ...

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Embedding determinista offline (hash → vector). NO semántico real.

    Útil para dev, tests y como fallback cuando no hay API key. Produce el
    mismo vector para el mismo texto (determinista), permitiendo búsqueda
    por similitud coseno coherente dentro de una corrida. NO usar en prod
    como única fuente de verdad semántica; combinar con BM25 (hybrid).
    """

    def __init__(self, dim: int = 256, seed: int = 0) -> None:
        self.dim = dim
        self._seed = seed

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            # Mezcla varias fragmentaciones del hash para dispersar.
            for window in range(0, max(1, len(text)), max(1, len(text) // self.dim or 1)):
                chunk = text[window : window + 8]
                h = hashlib.sha256(f"{self._seed}:{chunk}".encode("utf-8")).digest()
                for i in range(0, len(h), 4):
                    idx = (h[i] + h[i + 1] * 256) % self.dim
                    sign = 1.0 if (h[i + 2] & 1) == 0 else -1.0
                    vec[idx] += sign * ((h[i + 3] % 100) / 100.0)
            # Normaliza a norma 1 para coseno estable.
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embeddings reales vía OpenAI (opt-in, import diferido).

    Requiere ``openai`` instalado y ``OPENAI_API_KEY``. Degrada a excepción
    clara si no está disponible. No se importa en el default offline.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dim: int = 1536,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - depende de extra
            raise RuntimeError(
                "OpenAIEmbeddingProvider requiere el paquete 'openai'. "
                "Instálalo o usa DeterministicEmbeddingProvider (offline)."
            ) from exc
        self.dim = dim
        self._model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:  # pragma: no cover
        resp = self._client.embeddings.create(model=self._model, input=list(texts))
        return [list(d.embedding) for d in resp.data]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


__all__ = [
    "EmbeddingProvider",
    "DeterministicEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "cosine_similarity",
]
