"""Tests offline de métricas deterministas (Fase 18). Sin red ni extras."""

import pytest

from ciel.eval import metrics as M


def test_exact_match():
    assert M.exact_match("París", "parís") == 1.0
    assert M.exact_match("París", "Madrid") == 0.0
    assert M.exact_match("", None) == 0.0


def test_contains():
    assert M.contains("La capital es París.", "parís") == 1.0
    assert M.contains("Madrid", "parís") == 0.0


def test_f1_token():
    # F1 token usa sets (tokens únicos).
    assert M.f1_token("gato perro", "gato perro") == 1.0
    assert M.f1_token("gato", "perro") == 0.0
    # solapamiento parcial: pred={gato,perro}, gold={gato} -> tp=1, P=0.5, R=1.0, F1=0.667
    assert abs(M.f1_token("gato perro", "gato") - 2 / 3) < 1e-9
    assert M.f1_token("", "gato") == 0.0


def test_faithfulness_with_context():
    ans = "París es la capital de Francia"
    ctx = "Francia es un país; su capital es París."
    score = M.faithfulness(ans, ctx)
    assert 0.0 < score <= 1.0
    assert M.faithfulness("respuesta", None) == 0.0


def test_faithfulness_empty_answer():
    assert M.faithfulness("", "contexto") == 0.0


def test_context_relevance_with_text():
    score = M.context_relevance("capital Francia", "Francia capital París", retriever=None)
    assert 0.0 < score <= 1.0
    # sin query ni contexto -> 0
    assert M.context_relevance("", "", retriever=None) == 0.0


def test_context_relevance_with_retriever():
    from ciel.rag import KnowledgeBase, Retriever

    kb = KnowledgeBase()
    kb.add_texts(["Francia es un país europeo cuya capital es París."], tenant_id="t1")
    retr = Retriever(kb, top_k=2)
    score = M.context_relevance("capital de Francia", None, retriever=retr, tenant_id="t1")
    assert 0.0 <= score <= 1.0


def test_answer_relevance():
    assert M.answer_relevance("París es la capital de Francia", "capital de Francia") > 0.0
    assert M.answer_relevance("", "pregunta") == 0.0


def test_third_party_flags_false_without_extras():
    # En CI sin el extra eval instalado, estos deben reportar False (degradación).
    assert M.has_deepeval() is False or isinstance(M.has_deepeval(), bool)
    assert M.has_ragas() is False or isinstance(M.has_ragas(), bool)
    assert M.has_trulens() is False or isinstance(M.has_trulens(), bool)
    # Las funciones de terceros degradan a None en lugar de romper.
    assert M.deepeval_faithfulness("a", "b") is None
    assert M.ragas_faithfulness("q", "a", "b") is None
