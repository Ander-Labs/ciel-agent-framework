"""Prometheus metrics for Ciel (lenient).

This module is *optional* at runtime: if ``prometheus-client`` is not
installed (it lives behind the ``observability`` extra) every symbol here
still imports cleanly and the helpers provided (:func:`record_request`,
:func:`record_tool_call`, :func:`record_agent_loop`) become no-ops that
never raise. A single :func:`metrics_handler` is exposed so the gateway can
mount a ``/metrics`` endpoint that returns valid Prometheus text when the
client is available and a minimal 200 response otherwise.

Multi-tenancy is preserved by recording ``tenant`` as a label on every
metric that carries it.
"""

from __future__ import annotations

import logging
from typing import Optional

from starlette.responses import Response  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


# --- optional dependency resolution -------------------------------------
try:  # pragma: no cover - exercised only when prometheus-client is installed
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        REGISTRY,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except Exception as exc:  # pragma: no cover - exercised when prom missing
    logger.warning(
        "prometheus-client not installed; metrics disabled: %s", exc
    )
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = None  # type: ignore[assignment]
    REGISTRY = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]


__all__ = [
    "PROM_AVAILABLE",
    "record_request",
    "record_tool_call",
    "record_agent_loop",
    "metrics_handler",
    "generate_latest",
]


#: ``True`` when the prometheus_client package was importable at module load.
PROM_AVAILABLE = _PROM_AVAILABLE


# Metrics are created lazily so that a missing prometheus-client import does
# not raise at module load time.
if _PROM_AVAILABLE:  # pragma: no cover - exercised only when prom is installed
    _requests_total = Counter(
        "ciel_requests_total",
        "Total Ciel requests by surface, tenant and status.",
        ["surface", "tenant", "status"],
    )
    _tool_calls_total = Counter(
        "ciel_tool_calls_total",
        "Total Ciel tool invocations by tenant, tool and status.",
        ["tenant", "tool", "status"],
    )
    _agent_loops_total = Counter(
        "ciel_agent_loops_total",
        "Total Ciel agent loop iterations (optionally by tenant).",
        ["tenant"],
    )
else:  # pragma: no cover - exercised when prom is missing
    _requests_total = None
    _tool_calls_total = None
    _agent_loops_total = None


def record_request(
    surface: str,
    tenant: Optional[str],
    status: str,
    *,
    increment: int = 1,
) -> None:
    """Increment ``ciel_requests_total``.

    Safe no-op when prometheus-client is unavailable or an error occurs.
    """
    if not _PROM_AVAILABLE or _requests_total is None:
        return
    try:
        _requests_total.labels(
            surface=surface, tenant=tenant or "_global", status=status
        ).inc(increment)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("record_request failed: %s", exc)


def record_tool_call(
    tool: str,
    tenant: Optional[str],
    status: str,
    *,
    increment: int = 1,
) -> None:
    """Increment ``ciel_tool_calls_total``.

    Safe no-op when prometheus-client is unavailable or an error occurs.
    """
    if not _PROM_AVAILABLE or _tool_calls_total is None:
        return
    try:
        _tool_calls_total.labels(
            tool=tool, tenant=tenant or "_global", status=status
        ).inc(increment)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("record_tool_call failed: %s", exc)


def record_agent_loop(tenant: Optional[str] = None, *, increment: int = 1) -> None:
    """Increment ``ciel_agent_loops_total``.

    Safe no-op when prometheus-client is unavailable or an error occurs.
    """
    if not _PROM_AVAILABLE or _agent_loops_total is None:
        return
    try:
        _agent_loops_total.labels(tenant=tenant or "_global").inc(increment)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("record_agent_loop failed: %s", exc)


async def metrics_handler(request=None) -> Response:
    """Starlette/FastAPI handler exposing ``/metrics``.

    Returns Prometheus text exposition when the client is available. When it
    is not, returns a 200 response with a short notice so the endpoint still
    resolves without crashing the gateway (offline-safe).
    """
    if _PROM_AVAILABLE and generate_latest is not None:  # pragma: no cover
        body = generate_latest(REGISTRY)
        return Response(content=body, media_type=CONTENT_TYPE_LATEST)
    return Response(
        content="# ciel metrics: prometheus-client not installed\n",
        media_type=CONTENT_TYPE_LATEST,
    )
