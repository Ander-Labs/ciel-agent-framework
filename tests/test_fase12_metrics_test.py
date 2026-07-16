"""Fase 12 — Skill Performance Metrics (Item 6).

Offline tests (no network, no API keys) covering :class:`SkillMetrics`:
record_usage increments calls, success_rate is computed, avg_latency is
computed, and tenant isolation is respected when tenant_id is supplied.
"""

from __future__ import annotations

import pytest

from ciel.runtime.skill_metrics import SkillMetrics


def test_record_usage_increments_calls():
    m = SkillMetrics()
    m.record_usage("lib", "add", success=True, latency_ms=10.0)
    m.record_usage("lib", "add", success=True, latency_ms=20.0)
    assert m.metrics("add")["calls"] == 2


def test_success_rate_is_calculated():
    m = SkillMetrics()
    m.record_usage("lib", "add", success=True)
    m.record_usage("lib", "add", success=True)
    m.record_usage("lib", "add", success=False)
    out = m.metrics("add")
    assert out["calls"] == 3
    assert out["successes"] == 2
    assert out["failures"] == 1
    # 2 successes / 3 calls
    assert out["success_rate"] == pytest.approx(2 / 3)


def test_avg_latency_is_calculated():
    m = SkillMetrics()
    m.record_usage("lib", "add", success=True, latency_ms=10.0)
    m.record_usage("lib", "add", success=True, latency_ms=20.0)
    m.record_usage("lib", "add", success=True, latency_ms=30.0)
    out = m.metrics("add")
    assert out["avg_latency_ms"] == pytest.approx(20.0)


def test_unknown_skill_returns_zeroes():
    m = SkillMetrics()
    out = m.metrics("missing")
    assert out == {
        "calls": 0,
        "successes": 0,
        "failures": 0,
        "success_rate": 0.0,
        "avg_latency_ms": 0.0,
    }


def test_tenant_isolation_optional():
    m = SkillMetrics()
    # Same skill name, two different tenants -> independent counters.
    m.record_usage("lib", "add", success=True, latency_ms=5.0, tenant_id="tenant-a")
    m.record_usage("lib", "add", success=False, latency_ms=7.0, tenant_id="tenant-b")
    m.record_usage("lib", "add", success=True, latency_ms=9.0, tenant_id="tenant-a")

    a = m.metrics("add", tenant_id="tenant-a")
    b = m.metrics("add", tenant_id="tenant-b")

    assert a["calls"] == 2
    assert a["successes"] == 2
    assert a["failures"] == 0
    assert a["avg_latency_ms"] == pytest.approx(7.0)  # (5 + 9) / 2

    assert b["calls"] == 1
    assert b["successes"] == 0
    assert b["failures"] == 1
    assert b["avg_latency_ms"] == pytest.approx(7.0)

    # Global (no tenant) scope stays separate from tenant scopes.
    assert m.metrics("add")["calls"] == 0


def test_tenant_metrics_independent_of_global():
    m = SkillMetrics()
    m.record_usage("lib", "add", success=True, latency_ms=1.0)
    m.record_usage("lib", "add", success=True, latency_ms=3.0, tenant_id="t1")
    assert m.metrics("add")["calls"] == 1
    assert m.metrics("add", tenant_id="t1")["calls"] == 1
