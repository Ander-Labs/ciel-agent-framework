"""Carga de datasets de evaluación desde YAML (Fase 18).

Formato esperado (lista de casos):

    - query: "¿Capital de Francia?"
      expected: "París"
      context: "Francia es un país de Europa; su capital es París."
    - query: "¿2+2?"
      expected: "4"

Offline-safe: solo lee el archivo local, sin red.
"""

from __future__ import annotations

import os
from typing import Any, List

import yaml

from ciel.eval.eval_case import EvalCase


def load_dataset(path: str) -> List[EvalCase]:
    """Carga un dataset YAML de casos de evaluación.

    Args:
        path: ruta al archivo YAML. Puede ser una lista de dicts o un dict con
            una clave ``cases`` que sea la lista.

    Returns:
        lista de ``EvalCase``.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset de evaluación no encontrado: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    raw: Any
    if isinstance(data, dict):
        raw = data.get("cases", [])
    elif isinstance(data, list):
        raw = data
    else:
        raise ValueError(f"Dataset inválido en {path}: se esperaba lista o dict con 'cases'")
    cases: List[EvalCase] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Caso #{i} inválido en {path}: debe ser un dict")
        cases.append(
            EvalCase(
                query=str(item.get("query", "")),
                expected=item.get("expected"),
                context=item.get("context"),
                gold=item.get("gold"),
                metadata=item.get("metadata", {}) or {},
            )
        )
    return cases
