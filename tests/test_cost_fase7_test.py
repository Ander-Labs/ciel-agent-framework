"""Tests Fase 7 — ciel.enterprise.cost (CostGovernor).

OFFLINE-SAFE: estado en memoria, sin red ni proveedor.
"""

from __future__ import annotations

import pytest

from ciel.enterprise.cost import (
    BudgetExceededError,
    CostGovernor,
    ModelCost,
)

MODELS = {
    "gpt-4o": ModelCost(per_1k_input=0.005, per_1k_output=0.015),
    "echo": ModelCost(per_1k_input=0.0, per_1k_output=0.0),
}


def _gov(budgets=None, alert_threshold=0.8):
    return CostGovernor(
        budgets=budgets if budgets is not None else {"*": 10.0},
        models=dict(MODELS),
        alert_threshold=alert_threshold,
    )


def test_estimate_computes_correctly():
    gov = _gov()
    # 1000 in * 0.005/1k = 0.005 ; 1000 out * 0.015/1k = 0.015 => 0.02
    assert gov.estimate("gpt-4o", 1000, 1000) == pytest.approx(0.02)
    assert gov.estimate("echo", 1000, 1000) == pytest.approx(0.0)
    with pytest.raises(Exception):
        gov.estimate("unknown-model", 1, 1)


def test_record_accumulates_spend():
    gov = _gov()
    first = gov.record("t1", "gpt-4o", 1000, 1000)  # 0.02
    second = gov.record("t1", "gpt-4o", 1000, 1000)  # otro 0.02
    assert first == pytest.approx(0.02)
    assert second == pytest.approx(0.04)
    assert gov.spent("t1") == pytest.approx(0.04)


def test_allowed_true_before_limit_then_false():
    # presupuesto ajustado para cruzarlo con pocas llamadas
    gov = CostGovernor(
        budgets={"*": 0.05},
        models=dict(MODELS),
    )
    # 0.02 + 0.02 = 0.04 <= 0.05 => allowed
    assert gov.allowed("t1", "gpt-4o", 1000, 1000) is True
    gov.record("t1", "gpt-4o", 1000, 1000)  # ahora 0.02
    gov.record("t1", "gpt-4o", 1000, 1000)  # ahora 0.04
    # siguiente llamada de 0.02 proyectaría 0.06 > 0.05 => denied
    assert gov.allowed("t1", "gpt-4o", 1000, 1000) is False


def test_check_budget_raises_when_exceeded():
    gov = CostGovernor(budgets={"*": 0.03}, models=dict(MODELS))
    gov.record("t1", "gpt-4o", 1000, 1000)  # 0.02
    # próxima de 0.02 => 0.04 > 0.03
    with pytest.raises(BudgetExceededError):
        gov.check_budget("t1", "gpt-4o", 1000, 1000)


def test_global_budget_applies_to_unset_tenant():
    gov = CostGovernor(budgets={"*": 0.05}, models=dict(MODELS))
    assert gov.budget_of("tenant-sin-presupuesto") == pytest.approx(0.05)
    assert gov.remaining("tenant-sin-presupuesto") == pytest.approx(0.05)


def test_alerted_after_threshold():
    gov = _gov(budgets={"*": 0.10}, alert_threshold=0.8)
    # 80% de 0.10 = 0.08. Cada llamada 0.02 => 5 llamadas = 0.10 (> 0.08)
    for _ in range(5):
        gov.record("t1", "gpt-4o", 1000, 1000)
    assert gov.spent("t1") == pytest.approx(0.10)
    assert gov.alerted("t1") is True
    # antes del umbral no alerta (3 llamadas = 0.06 < 0.08)
    gov2 = _gov(budgets={"*": 0.10}, alert_threshold=0.8)
    gov2.record("t1", "gpt-4o", 1000, 1000)
    gov2.record("t1", "gpt-4o", 1000, 1000)
    gov2.record("t1", "gpt-4o", 1000, 1000)
    assert gov2.alerted("t1") is False
