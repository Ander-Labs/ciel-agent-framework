"""ciel.eval — capa de evaluación y testing reproducible (Fase 18).

Offline-safe por defecto: métricas deterministas propias funcionan sin red ni
extras. DeepEval/RAGAS/TruLens son opt-in vía el extra ``eval``; si no están
instalados, ``Evaluator`` degrada a métricas propias (igual que LiteLLM/RAG).
"""

from __future__ import annotations

from ciel.eval.eval_case import EvalCase
from ciel.eval.metrics import (
    answer_relevance,
    context_relevance,
    contains,
    exact_match,
    faithfulness,
    f1_token,
)
from ciel.eval.evaluator import EvalResult, Evaluator
from ciel.eval.datasets import load_dataset

__all__ = [
    "EvalCase",
    "Evaluator",
    "EvalResult",
    "exact_match",
    "contains",
    "f1_token",
    "faithfulness",
    "context_relevance",
    "answer_relevance",
    "load_dataset",
]
