"""OpenTelemetry audit exporter and tracing bootstrap (lenient).

This module is *optional* at runtime: if the ``opentelemetry-api`` /
``opentelemetry-sdk`` packages are not installed (they live behind the
``observability`` extra) every symbol here still imports cleanly. The
:class:`OtlpAuditExporter` degrades to a no-op sink and :func:`init_tracing`
returns ``None`` while logging a warning, so callers never need to guard
imports themselves.

When the packages *are* present, :class:`OtlpAuditExporter` implements the
:class:`~ciel.observability.AuditSink` interface and emits an OpenTelemetry
span (plus a span event) for every :class:`~ciel.observability.AuditEvent` it
receives, preserving multi-tenancy via ``tenant_id`` span attributes.

Fase 8 añade helpers de observabilidad centralizada:
:func:`init_tracing` acepta un ``otlp_endpoint`` (exportador OTLP a un
colector) o, por defecto, un ``InMemorySpanExporter`` para tests offline;
:func:`span_count` cuenta los spans exportados (usado por los tests);
:func:`current_tracer` devuelve el tracer global.
"""

from __future__ import annotations

import logging
from typing import Optional

from ciel.observability import AuditEvent, AuditSink

logger = logging.getLogger(__name__)


# --- optional dependency resolution -------------------------------------
try:  # pragma: no cover - exercised only when otel is installed
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    _OTEL_AVAILABLE = True
except Exception as exc:  # pragma: no cover - exercised when otel missing
    logger.warning(
        "opentelemetry not installed; OpenTelemetry export disabled: %s", exc
    )
    _OTEL_AVAILABLE = False
    trace = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    SERVICE_NAME = None  # type: ignore[assignment]
    SimpleSpanProcessor = None  # type: ignore[assignment]
    InMemorySpanExporter = None  # type: ignore[assignment]


__all__ = [
    "OtlpAuditExporter",
    "init_tracing",
    "OTEL_AVAILABLE",
    "current_tracer",
    "span_count",
]


#: ``True`` when the opentelemetry packages were importable at module load.
OTEL_AVAILABLE = _OTEL_AVAILABLE

#: Reference to the last TracerProvider installed by :func:`init_tracing`, so
#: :func:`span_count` can inspect the real exporter instead of the global proxy.
_last_provider = None


def _import_otlp_exporter():
    """Best-effort import of an OTLP span exporter (lenient).

    Tries the gRPC exporter first, then the HTTP/protobuf one. Returns the
    exporter class or ``None`` if neither is installed.
    """
    try:  # pragma: no cover - depends on optional extras
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter
    except Exception:
        pass
    try:  # pragma: no cover - depends on optional extras
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter
    except Exception:
        return None


def init_tracing(
    *,
    service_name: str = "ciel",
    otlp_endpoint: Optional[str] = None,
) -> Optional["TracerProvider"]:
    """Configure and install a global OpenTelemetry :class:`TracerProvider`.

    Parameters
    ----------
    service_name:
        Value for the ``service.name`` resource attribute.
    otlp_endpoint:
        If given, spans are exported to this OTLP collector endpoint. If the
        OTLP exporter packages are not installed the call degrades to an
        in-memory exporter and logs a warning. If ``None``, an in-memory
        exporter is used so the gateway is still bootable offline.

    Returns
    -------
    TracerProvider | None
        The installed provider, or ``None`` when opentelemetry is unavailable.
    """
    if not _OTEL_AVAILABLE:  # pragma: no cover - depends on optional extras
        logger.warning("init_tracing: opentelemetry unavailable; tracing disabled")
        return None

    resource = Resource.create({SERVICE_NAME: service_name})
    provider: "TracerProvider" = TracerProvider(resource=resource)

    if otlp_endpoint:
        exporter_cls = _import_otlp_exporter()
        if exporter_cls is not None:  # pragma: no cover - needs otlp exporter
            provider.add_span_processor(
                SimpleSpanProcessor(exporter_cls(endpoint=otlp_endpoint))
            )
            logger.info("tracing: OTLP exporter configured for %s", otlp_endpoint)
        else:  # pragma: no cover - needs missing exporter
            logger.warning(
                "tracing: OTLP endpoint set but no OTLP exporter installed; "
                "falling back to in-memory exporter"
            )
            provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    else:
        provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))

    trace.set_tracer_provider(provider)
    # Guardamos la referencia real (global) para que span_count() no dependa
    # del proxy global (get_tracer_provider puede devolver un
    # ProxyTracerProvider si aún no se ha configurado).
    global _last_provider
    _last_provider = provider
    return provider


def _find_in_memory_exporter(provider) -> Optional["InMemorySpanExporter"]:
    """Navega la estructura real del TracerProvider 1.x para hallar el
    ``InMemorySpanExporter``.

    En opentelemetry-sdk 1.x el provider NO expone ``active_span_processor``
    publico: usa ``_active_span_processor`` (un ``SynchronousMultiSpanProcessor``
    o ``ConcurrentMultiSpanProcessor``) que contiene ``_span_processors`` (lista)
    y cada processor tiene ``span_exporter``. Devuelve el primero que sea
    ``InMemorySpanExporter`` o ``None``.
    """
    if provider is None:
        return None
    asp = getattr(provider, "_active_span_processor", None)
    if asp is None:
        return None
    processors = getattr(asp, "_span_processors", None)
    if not processors:
        # Un processor unico (no multi) tambien es posible.
        single = getattr(asp, "span_exporter", None)
        return single if isinstance(single, InMemorySpanExporter) else None
    for proc in processors:
        exporter = getattr(proc, "span_exporter", None)
        if isinstance(exporter, InMemorySpanExporter):
            return exporter
    return None


def current_tracer():
    """Devuelve el tracer global de OTel, o ``None`` si OTel no está disponible.

    Útil para que el gateway/emisiones de trazas obtengan el tracer sin
    importar opcionales.
    """
    if not _OTEL_AVAILABLE:
        return None
    return trace.get_tracer("ciel")


def span_count() -> int:
    """Número de spans emitidos por el exporter in-memory (solo tests/diagnóstico).

    Si el provider global fue configurado con ``InMemorySpanExporter`` (el
    caso por defecto de ``init_tracing`` sin endpoint), devuelve cuántos
    spans se han exportado. Si OTel no está disponible o el exporter no es
    in-memory, devuelve ``-1`` (no medible de forma determinista).
    """
    if not _OTEL_AVAILABLE:
        return -1
    provider = _last_provider or trace.get_tracer_provider()
    exporter = _find_in_memory_exporter(provider)
    if exporter is not None:
        return len(exporter.get_finished_spans())
    return -1


class OtlpAuditExporter(AuditSink):
    """Audit sink that forwards events to an OpenTelemetry tracer.

    Every :meth:`write` call starts a span named after ``event.event`` and
    attaches a span event carrying the event payload. Multi-tenancy is
    preserved by recording ``tenant_id`` (and ``session_id`` / ``agent`` /
    ``tool_call_id`` when present) as span attributes.

    The sink is *safe*: a missing opentelemetry install makes :meth:`write` a
    no-op, and any tracing error is swallowed after logging so audit emission
    never crashes the caller.
    """

    def __init__(
        self,
        *,
        tracer=None,
        service_name: str = "ciel",
    ) -> None:
        if _OTEL_AVAILABLE and tracer is None:
            tracer = trace.get_tracer(service_name)
        self._tracer = tracer
        self.service_name = service_name

    async def write(self, event: AuditEvent) -> None:
        if not _OTEL_AVAILABLE or self._tracer is None:
            return
        try:
            with self._tracer.start_as_current_span(event.event) as span:
                if event.tenant_id is not None:
                    span.set_attribute("tenant.id", event.tenant_id)
                if event.session_id is not None:
                    span.set_attribute("session.id", event.session_id)
                if event.agent is not None:
                    span.set_attribute("agent.name", event.agent)
                if event.tool_call_id is not None:
                    span.set_attribute("tool.call.id", event.tool_call_id)
                attributes = {
                    "event": event.event,
                    "tenant.id": event.tenant_id or "",
                }
                if event.data:
                    for key, value in event.data.items():
                        safe_key = key.replace(".", "_")[:64]
                        try:
                            span.set_attribute(f"event.data.{safe_key}", str(value))
                            attributes[f"data.{safe_key}"] = str(value)
                        except Exception:  # pragma: no cover - defensive
                            pass
                span.add_event(event.event, attributes=attributes)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("OtlpAuditExporter.write failed: %s", exc)
