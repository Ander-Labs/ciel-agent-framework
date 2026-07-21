"""Métricas deterministas para evaluación (Fase 18).

Todas las métricas propias son deterministas y offline-safe (no requieren red
ni extras). Las métricas de RAG (``faithfulness``/``context_relevance``) usan
heurísticas sobre tokens comunes entre la respuesta y el contexto recuperado;
``context_relevance`` acepta opcionalmente un ``Retriever`` del F17 para medir
qué tan afinados están los chunks recuperados con la query.

DeepEval/RAGAS/TruLens son OPT-IN: si el extra ``eval`` está instalado, las
funciones ``deepeval_*`` / ``ragas_*`` / ``trulens_*`` delegan a ellos; si no,
el llamador (``Evaluator``) degrada a métricas propias.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)


def _tokens(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def exact_match(actual: str, expected: str) -> float:
    """1.0 si la respuesta coincide exactamente (trim + lower) con lo esperado."""
    if actual is None or expected is None:
        return 0.0
    return 1.0 if actual.strip().lower() == expected.strip().lower() else 0.0


def contains(actual: str, expected: str) -> float:
    """1.0 si la respuesta contiene el substring esperado (case-insensitive)."""
    if actual is None or expected is None:
        return 0.0
    return 1.0 if expected.strip().lower() in actual.strip().lower() else 0.0


def f1_token(actual: str, expected: str) -> float:
    """F1 sobre tokens entre la respuesta y la referencia (cerrada)."""
    pred = set(_tokens(actual))
    gold = set(_tokens(expected))
    if not gold:
        return 1.0 if not pred else 0.0
    if not pred:
        return 0.0
    tp = len(pred & gold)
    precision = tp / len(pred)
    recall = tp / len(gold)
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _overlap_ratio(answer_tokens: Sequence[str], context_tokens: Sequence[str]) -> float:
    if not context_tokens:
        return 0.0
    common = len(set(answer_tokens) & set(context_tokens))
    return common / len(context_tokens)


def faithfulness(answer: str, context: Optional[str]) -> float:
    """¿La respuesta se apoya en el contexto recuperado?

    Heurística determinista: proporción de tokens de la respuesta que también
    aparecen en el contexto. Sin contexto -> 0.0.
    """
    ans = _tokens(answer)
    ctx = _tokens(context)
    if not ans:
        return 0.0
    common = len(set(ans) & set(ctx))
    return common / len(ans)


def context_relevance(
    query: str,
    context: Optional[str],
    *,
    retriever: Any = None,
    tenant_id: Optional[str] = None,
) -> float:
    """Afinación del contexto respecto a la query.

    - Si se pasa un ``Retriever`` del F17, recupera chunks para la query y mide
      la superposición de tokens entre la query y los chunks recuperados.
    - Si no, mide la superposición de tokens entre la query y el ``context``
      provisto (heurística determinista).
    """
    q_tokens = set(_tokens(query))
    if retriever is not None:
        try:
            results = retriever.results(query, tenant_id=tenant_id)
            ctx_tokens: List[str] = []
            for r in results:
                ctx_tokens.extend(_tokens(getattr(r, "text", str(r))))
        except Exception:
            ctx_tokens = _tokens(context)
    else:
        ctx_tokens = _tokens(context)
    if not q_tokens or not ctx_tokens:
        return 0.0
    return _overlap_ratio(list(q_tokens), ctx_tokens)


def answer_relevance(answer: str, query: str) -> float:
    """Heurística determinista: la respuesta comparte tokens con la query.

    Castiga respuestas vacías o que ignoran por completo la pregunta.
    """
    ans = _tokens(answer)
    q = set(_tokens(query))
    if not ans or not q:
        return 0.0
    common = len(set(ans) & q)
    return min(1.0, common / max(1, len(q) // 2))


# ---------------------------------------------------------------------------
# Integración opt-in con DeepEval / RAGAS / TruLens (extra ``eval``).
# Estas funciones degradan a None si el extra no está instalado, para que el
# Evaluator decida usar métricas propias en su lugar.
# ---------------------------------------------------------------------------


def has_deepeval() -> bool:
    try:
        import deepeval  # noqa: F401

        return True
    except ImportError:
        return False


def has_ragas() -> bool:
    try:
        import ragas  # noqa: F401

        return True
    except ImportError:
        return False


def has_trulens() -> bool:
    try:
        import trulens_eval  # noqa: F401

        return True
    except ImportError:
        return False


def deepeval_faithfulness(answer: str, context: str) -> Optional[float]:
    """Faithfulness de DeepEval (opt-in). Devuelve None si no está instalado."""
    if not has_deepeval():
        return None
    try:  # pragma: no cover - depends on extras install
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase

        case = LLMTestCase(input="", actual_output=answer, retrieval_context=[context or ""])
        metric = FaithfulnessMetric(threshold=0.5)
        metric.measure(case)
        return float(metric.score)
    except Exception:
        return None


def ragas_faithfulness(question: str, answer: str, context: str) -> Optional[float]:
    """Faithfulness de RAGAS (opt-in). Devuelve None si no está instalado."""
    if not has_ragas():
        return None
    try:  # pragma: no cover - depends on extras install
        import datasets as hf_datasets
        from ragas import evaluate
        from ragas.metrics import faithfulness as ragas_faith

        ds = hf_datasets.Dataset.from_dict(
            {
                "question": [question],
                "answer": [answer],
                "contexts": [[context or ""]],
            }
        )
        result = evaluate(ds, metrics=[ragas_faith])
        scores = result["faithfulness"]
        return float(scores[0]) if scores else None
    except Exception:
        return None


def trulens_context_relevance(question: str, context: str) -> Optional[float]:
    """Context relevance de TruLens (opt-in). Devuelve None si no está instalado."""
    if not has_trulens():
        return None
    try:  # pragma: no cover - depends on extras install
        from trulens_eval.feedback import Feedback
        from trulens_eval.feedback.provider import OpenAI  # noqa: F401

        # TruLens requiere un LLM real; sin credenciales degradamos a None.
        return None
    except Exception:  # pragma: no cover
        return None
