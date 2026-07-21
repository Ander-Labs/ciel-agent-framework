"""Tests offline del Evaluator (Fase 18). Usa MockProvider como evaluable."""

import json
import os

import pytest

from ciel.eval import EvalCase, Evaluator, load_dataset
from ciel.providers import MockProvider
from ciel.runtime import ChatRequest, ChatMessage

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fixed_provider(resp: str) -> MockProvider:
    return MockProvider(mode="fixed", response=resp)


async def _callable(query: str, **kw) -> str:
    p = _fixed_provider(kw.get("__resp", "París"))
    r = await p.complete(ChatRequest(messages=[ChatMessage(role="user", content=query)]))
    return r.choice.message.content


def test_load_dataset_smoke():
    ds = load_dataset(os.path.join(REPO, "tests", "eval", "smoke.yaml"))
    assert len(ds) == 3
    assert all(isinstance(c, EvalCase) for c in ds)
    assert ds[0].query and ds[0].expected


def test_evaluator_runs_with_mock_callable():
    cases = [
        EvalCase(query="q1", expected="París"),
        EvalCase(query="q2", expected="4"),
    ]

    async def agent(query, **kw):
        return "París" if "q1" in query else "4"

    ev = Evaluator(agent=agent)
    results = ev.run(cases, threshold=0.8)
    assert len(results) == 2
    assert all(r.passed for r in results)
    kpis = ev.kpis()
    assert kpis["n"] == 2
    assert kpis["pass_rate"] == 1.0
    assert kpis["metrics"]["exact_match"] == 1.0


def test_evaluator_fails_below_threshold():
    cases = [EvalCase(query="q", expected="París")]

    async def agent(query, **kw):
        return "Madrid"

    ev = Evaluator(agent=agent)
    results = ev.run(cases, threshold=0.8)
    assert results[0].passed is False
    assert ev.kpis()["pass_rate"] == 0.0


def test_evaluator_with_rag_context_metrics():
    cases = [
        EvalCase(
            query="capital Francia",
            expected="París",
            context="Francia es un país; su capital es París.",
        )
    ]

    async def agent(query, **kw):
        return "París es la capital de Francia"

    ev = Evaluator(agent=agent)
    ev.run(cases, threshold=0.5)
    scores = ev.results[0].scores
    assert "faithfulness" in scores
    assert "answer_relevance" in scores
    assert scores["faithfulness"] > 0.0


def test_evaluator_handles_agent_error_gracefully():
    cases = [EvalCase(query="q", expected="x")]

    async def agent(query, **kw):
        raise RuntimeError("boom")

    ev = Evaluator(agent=agent)
    results = ev.run(cases, threshold=0.8)
    assert results[0].passed is False
    assert results[0].error is not None


def test_evaluator_export_writes_results_json(tmp_path):
    cases = [EvalCase(query="q", expected="París")]

    async def agent(query, **kw):
        return "París"

    ev = Evaluator(agent=agent)
    ev.run(cases, threshold=0.8)
    out = tmp_path / "results.json"
    payload = ev.export(str(out))
    assert out.exists()
    assert payload["kpis"]["n"] == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "results" in data and "kpis" in data
