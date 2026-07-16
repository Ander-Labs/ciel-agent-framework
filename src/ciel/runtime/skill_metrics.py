from __future__ import annotations

"""Skill Performance Metrics (Fase 12 — Autonomy I, Item 6).

Offline, in-memory performance tracking for skills. Records per-skill usage
(call counts, successes, failures, success rate and average latency) and keeps
the data isolated per optional ``tenant_id`` so tenants never see each other's
metrics.

Everything here is network-free and API-key-free so it can be exercised by
offline tests (the same convention as Fases 10/11/12).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class _SkillStat:
    """Accumulated metrics for a single skill (within one tenant scope)."""

    calls: int = 0
    successes: int = 0
    failures: int = 0
    _latency_sum_ms: float = 0.0

    def record(self, *, success: bool, latency_ms: float) -> None:
        self.calls += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self._latency_sum_ms += float(latency_ms)

    @property
    def success_rate(self) -> float:
        if self.calls == 0:
            return 0.0
        return self.successes / self.calls

    @property
    def avg_latency_ms(self) -> float:
        if self.calls == 0:
            return 0.0
        return self._latency_sum_ms / self.calls

    def as_dict(self) -> Dict[str, float]:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
        }


class SkillMetrics:
    """In-memory performance metrics for skills, optionally isolated by tenant.

    Usage::

        metrics = SkillMetrics()
        metrics.record_usage("lib", "add", success=True, latency_ms=12.5)
        print(metrics.metrics("add"))
        # {'calls': 1, 'successes': 1, 'failures': 0,
        #  'success_rate': 1.0, 'avg_latency_ms': 12.5}

    The ``lib`` argument records which skill library/source emitted the call
    (kept for traceability) while ``name`` is the key the metrics are stored
    under. When ``tenant_id`` is supplied, metrics are kept in a separate
    namespace so two tenants with the same skill name never share counters.
    """

    def __init__(self) -> None:
        # tenant_id (or "" for the global scope) -> name -> _SkillStat
        self._store: Dict[str, Dict[str, _SkillStat]] = {}

    def _scope(self, tenant_id: Optional[str]) -> Dict[str, _SkillStat]:
        key = tenant_id if tenant_id is not None else ""
        return self._store.setdefault(key, {})

    def record_usage(
        self,
        lib: str,
        name: str,
        success: bool,
        latency_ms: float = 0.0,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Record one skill invocation.

        ``lib`` identifies the originating library/source (stored for
        traceability but does not affect the metric key). ``name`` is the
        skill name the metrics are aggregated under. ``success`` marks the
        outcome and ``latency_ms`` is the observed latency. ``tenant_id``
        optionally isolates the record into a tenant-specific namespace.
        """
        scope = self._scope(tenant_id)
        stat = scope.get(name)
        if stat is None:
            stat = _SkillStat()
            scope[name] = stat
        stat.record(success=success, latency_ms=latency_ms)

    def metrics(self, name: str, tenant_id: Optional[str] = None) -> Dict[str, float]:
        """Return aggregated metrics for ``name`` as a dict.

        Returns ``{calls, successes, failures, success_rate, avg_latency_ms}``.
        Unknown skills return all-zero counters (success_rate 0.0) rather than
        raising, so callers can read metrics before any usage has been recorded.
        """
        scope = self._scope(tenant_id)
        stat = scope.get(name)
        if stat is None:
            return {
                "calls": 0,
                "successes": 0,
                "failures": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
            }
        return stat.as_dict()

    def reset(self, *, tenant_id: Optional[str] = None) -> None:
        """Clear recorded metrics.

        With ``tenant_id`` only that tenant's namespace is cleared; with no
        tenant_id the global (non-tenant) namespace is cleared.
        """
        key = tenant_id if tenant_id is not None else ""
        self._store[key] = {}
