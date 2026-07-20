"""Cargadores de documentos para RAG (Pilar C — Fase 17).

Offline-safe: MD/HTML/TXT se parsean sin dependencias. PDF requiere el extra
``rag`` (``pypdf``/``unstructured``) e importa de forma diferida.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class Document:
    """Un documento cargado, con texto y metadatos."""

    text: str
    source: str
    metadata: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


def load_text(path: str) -> Document:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return Document(text=text, source=path, metadata={"type": "text"})


def load_markdown(path: str) -> Document:
    return Document(
        text=load_text(path).text, source=path, metadata={"type": "markdown"}
    )


def load_html(path: str) -> Document:
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    # Strip de tags básico offline (sin dependencias).
    import re

    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return Document(text=text, source=path, metadata={"type": "html"})


def load_pdf(path: str) -> Document:
    """Carga un PDF (requiere extra ``rag`` con ``pypdf``)."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "load_pdf requiere el extra 'rag' (pip install 'mana-ciel[rag]')."
        ) from exc
    reader = PdfReader(path)
    parts: List[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return Document(
        text="\n".join(parts), source=path, metadata={"type": "pdf"}
    )


def load_document(path: str) -> Document:
    """Despacha por extensión."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".md":
        return load_markdown(path)
    if ext == ".html" or ext == ".htm":
        return load_html(path)
    if ext == ".pdf":
        return load_pdf(path)
    return load_text(path)


def load_documents(paths: Iterable[str]) -> List[Document]:
    return [load_document(p) for p in paths]


__all__ = [
    "Document",
    "load_text",
    "load_markdown",
    "load_html",
    "load_pdf",
    "load_document",
    "load_documents",
]
