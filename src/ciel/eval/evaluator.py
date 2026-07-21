"""Evaluator: orquesta la evaluación de un agente/callable sobre un dataset (Fase 18).

Offline-safe por defecto (métricas propias deterministas). Delega a
DeepEval/RAGAS/TruLens SOLO si el extra ``eval`` está instalado; si no, degrada
a métricas propias.

El agente/callable evaluable puede ser:
- un ``ciel.Agent`` (se llama ``agent.run(query, tenant_id=...)``),
- una corutina ``async def(query, *, tenant_id=None) -> str``,
- o una función síncrona ``def(query) -> str``.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ciel.eval.eval_case import EvalCase
from ciel.eval import metrics as M


@dataclass
class EvalResult:
    """Resultado de un caso individual."""

    query: str
    response: str
    expected: Optional[str]
    scores: Dict[str, float] = field(default_factory=dict)
    passed: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Evaluator:
    """Evalúa un agente/callable sobre un dataset y acumula KPIs."""

    def __init__(
        self,
        *,
        agent: Any = None,
        tenant_id: Optional[str] = None,
        use_third_party: bool = False,
        retriever: Any = None,
    ) -> None:
        self.agent = agent
        self.tenant_id = tenant_id
        self.use_third_party = use_third_party
        self.retriever = retriever
        self.results: List[EvalResult] = []

    # -- invocación del evaluable -------------------------------------------
    async def _call(self, case: EvalCase) -> str:
        agent = self.agent
        if agent is None:
            raise ValueError("Evaluator requiere un agent/callable (pasar agent=...)")
        # ciel.Agent
        if hasattr(agent, "arun") and callable(getattr(agent, "arun")):
            resp = await agent.arun(case.query, tenant_id=self.tenant_id)
            text = getattr(resp, "text", None)
            if text is None and hasattr(resp, "raw"):
                text = resp.raw.response.choice.message.text()
            return text or ""
        # corutina
        if asyncio.iscoroutinefunction(agent):
            return await agent(case.query, tenant_id=self.tenant_id) or ""
        # función síncrona / callable
        return agent(case.query) or ""

    # -- métricas -----------------------------------------------------------
    def _score(self, case: EvalCase, response: str) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        gold = case.gold_text()
        if gold is not None:
            scores["exact_match"] = M.exact_match(response, gold)
            scores["contains"] = M.contains(response, gold)
            scores["f1_token"] = M.f1_token(response, gold)
        if case.context is not None:
            scores["faithfulness"] = M.faithfulness(response, case.context)
            scores["context_relevance"] = M.context_relevance(
                case.query, case.context, retriever=self.retriever, tenant_id=self.tenant_id
            )
        scores["answer_relevance"] = M.answer_relevance(response, case.query)

        # Opt-in terceros (extra eval). Degradan a None si no instalados.
        if self.use_third_party and case.context is not None:
            de = M.deepeval_faithfulness(response, case.context)
            if de is not None:
                scores["deepeval_faithfulness"] = de
            rg = M.ragas_faithfulness(case.query, response, case.context)
            if rg is not None:
                scores["ragas_faithfulness"] = rg
        return scores

    # -- run ----------------------------------------------------------------
    async def arun(self, dataset: Sequence[EvalCase], *, threshold: float = 0.8) -> List[EvalResult]:
        out: List[EvalResult] = []
        for case in dataset:
            try:
                response = await self._call(case)
                scores = self._score(case, response)
                # ``answer_relevance`` es una métrica de diagnóstico (heurística
                # sobre tokens compartidos con la query); por defecto NO debe
                # hundir el caso en respuestas cerradas. El gating usa las demás.
                gating = {k: v for k, v in scores.items() if k != "answer_relevance"}
                passed = all(v >= threshold for v in gating.values()) if gating else True
                out.append(
                    EvalResult(
                        query=case.query,
                        response=response,
                        expected=case.expected,
                        scores=scores,
                        passed=passed,
                        metadata=dict(case.metadata),
                    )
                )
            except Exception as exc:  # degradación: el caso falla, no el eval
                out.append(
                    EvalResult(
                        query=case.query,
                        response="",
                        expected=case.expected,
                        scores={},
                        passed=False,
                        error=f"{type(exc).__name__}: {exc}",
                        metadata=dict(case.metadata),
                    )
                )
        self.results = out
        return out

    def run(self, dataset: Sequence[EvalCase], *, threshold: float = 0.8) -> List[EvalResult]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(dataset, threshold=threshold))
        raise RuntimeError("Evaluator.run() no puede usarse dentro de un event loop; usa arun()")

    # -- KPIs ---------------------------------------------------------------
    def kpis(self) -> Dict[str, Any]:
        if not self.results:
            return {"n": 0, "passed": 0, "failed": 0, "pass_rate": 0.0, "metrics": {}}
        n = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        agg: Dict[str, List[float]] = {}
        for r in self.results:
            for k, v in r.scores.items():
                agg.setdefault(k, []).append(v)
        metrics = {k: (sum(v) / len(v) if v else 0.0) for k, v in agg.items()}
        return {
            "n": n,
            "passed": passed,
            "failed": n - passed,
            "pass_rate": passed / n,
            "metrics": metrics,
        }

    def export(self, path: str) -> Dict[str, Any]:
        """Exporta resultados + KPIs a ``results.json``."""
        payload = {
            "kpis": self.kpis(),
            "results": [asdict(r) for r in self.results],
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        return payload
