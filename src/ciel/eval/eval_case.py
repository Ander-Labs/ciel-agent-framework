"""Definición de un caso de evaluación (Fase 18)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class EvalCase:
    """Un caso de evaluación.

    Args:
        query: entrada que se le pasa al agente/evaluable.
        expected: respuesta esperada (para métricas cerradas como ``exact_match``
            o ``contains``). Opcional si solo se evalúa ``faithfulness``/``answer_relevance``.
        context: contexto RAG recuperado (para ``faithfulness``/``context_relevance``).
        gold: respuesta "gold" alternativa para ``f1_token`` (por defecto usa ``expected``).
        metadata: metadatos libres (tenant, tags, etc.).
    """

    query: str
    expected: Optional[str] = None
    context: Optional[str] = None
    gold: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def gold_text(self) -> Optional[str]:
        """Texto gold efectivo (``gold`` o ``expected``)."""
        return self.gold if self.gold is not None else self.expected
