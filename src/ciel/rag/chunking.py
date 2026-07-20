"""Estrategias de chunking para RAG (Pilar C — Fase 17).

Offline-safe. Soporta chunking por tokens/caracteres con solapamiento y
chunking por párrafos (respetando límites semánticos). Thinking-mode friendly:
los chunks preservan el texto completo del documento de origen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence

from ciel.rag.loaders import Document


@dataclass
class Chunk:
    """Un fragmento indexable."""

    text: str
    doc_id: str
    chunk_index: int
    metadata: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


def chunk_by_tokens(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
) -> List[str]:
    """Chunking por tokens aproximados (split en espacios)."""
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    out: List[str] = []
    for i in range(0, len(words), step):
        out.append(" ".join(words[i : i + chunk_size]))
        if i + chunk_size >= len(words):
            break
    return out


def chunk_by_paragraphs(
    text: str,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 200,
) -> List[str]:
    """Chunking por párrafos; une párrafos hasta ``max_chars``."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: List[str] = []
    buf: List[str] = []
    total = 0
    for p in paras:
        if total + len(p) > max_chars and buf:
            out.append("\n\n".join(buf))
            # Solape: mantiene el último párrafo si cabe en overlap.
            if buf and len(buf[-1]) <= overlap_chars:
                buf = [buf[-1]]
                total = len(buf[-1])
            else:
                buf = []
                total = 0
        buf.append(p)
        total += len(p)
    if buf:
        out.append("\n\n".join(buf))
    return out


def chunk_document(
    doc: Document,
    *,
    strategy: str = "paragraph",
    chunk_size: int = 512,
    overlap: int = 64,
    max_chars: int = 1200,
    overlap_chars: int = 200,
) -> List[Chunk]:
    """Divide un ``Document`` en ``Chunk`` indexables."""
    if strategy == "token":
        pieces = chunk_by_tokens(doc.text, chunk_size=chunk_size, overlap=overlap)
    elif strategy == "paragraph":
        pieces = chunk_by_paragraphs(
            doc.text, max_chars=max_chars, overlap_chars=overlap_chars
        )
    else:
        raise ValueError(f"strategy desconocida: {strategy}")
    return [
        Chunk(
            text=piece,
            doc_id=doc.source,
            chunk_index=i,
            metadata={**doc.metadata, "chunk_index": i, "source": doc.source},
        )
        for i, piece in enumerate(pieces)
    ]


def chunk_documents(
    docs: Sequence[Document], **kwargs: object
) -> List[Chunk]:
    out: List[Chunk] = []
    for d in docs:
        out.extend(chunk_document(d, **kwargs))  # type: ignore[arg-type]
    return out


__all__ = ["Chunk", "chunk_by_tokens", "chunk_by_paragraphs", "chunk_document", "chunk_documents"]
