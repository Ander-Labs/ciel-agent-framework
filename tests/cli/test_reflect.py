"""Test de la CLI `ciel reflect` (Fase 19, v0.13.0).

Verifica la lógica pura ``run_reflection`` con ``MockProvider`` sobre el dataset
``tests/eval/smoke.yaml`` (offline, sin red). No usa CliRunner.
"""

from __future__ import annotations

from pathlib import Path

from ciel.cli.reflect import run_reflection

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "tests" / "eval" / "smoke.yaml"


def test_run_reflection_smoke_mock_threshold_zero():
    results, kpis = run_reflection(
        str(SMOKE), provider="mock", mock_response="París", threshold=0.0
    )
    assert isinstance(results, list)
    assert kpis["n"] >= 1
    # con threshold=0 todas las métricas gating pasan trivialmente
    assert kpis["pass_rate"] >= 0.0


def test_run_reflection_returns_kpis_keys():
    _results, kpis = run_reflection(str(SMOKE), provider="mock", threshold=0.0)
    for key in ("n", "passed", "failed", "pass_rate", "metrics"):
        assert key in kpis
