"""OpenTelemetry tracing setup and span helpers with secret sanitization."""

from contextlib import asynccontextmanager, contextmanager
import logging
from typing import Any, AsyncGenerator, Dict, Generator, Optional
from app.config import get_settings

logger = logging.getLogger(__name__)

_tracer = None


def sanitize_attributes(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize sensitive keys (tokens, passwords, api keys) before recording in spans."""
    clean: Dict[str, Any] = {}
    sensitive_patterns = {"key", "token", "password", "secret", "auth", "credential"}
    for k, v in attrs.items():
        if any(pat in k.lower() for pat in sensitive_patterns):
            clean[k] = "[REDACTED]"
        elif isinstance(v, (str, int, float, bool)):
            clean[k] = v
        else:
            clean[k] = str(v)[:250]
    return clean


def setup_telemetry(app: Optional[Any] = None) -> None:
    """Initialize OpenTelemetry tracer provider and instrumentations if enabled."""
    global _tracer
    settings = get_settings()

    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry is disabled by configuration (OTEL_ENABLED=false).")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME, "environment": settings.APP_ENV})
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer(settings.OTEL_SERVICE_NAME)

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)

        logger.info("OpenTelemetry successfully initialized for service: %s", settings.OTEL_SERVICE_NAME)
    except Exception as exc:
        logger.warning("Failed to initialize OpenTelemetry: %s. Continuing without OTel.", str(exc))


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Generator[Any, None, None]:
    """Synchronous context manager for creating an OpenTelemetry span (no-op if disabled)."""
    global _tracer
    if _tracer is None:
        yield None
        return

    clean_attrs = sanitize_attributes(attributes or {})
    with _tracer.start_as_current_span(name, attributes=clean_attrs) as span:
        yield span


@asynccontextmanager
async def async_trace_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> AsyncGenerator[Any, None]:
    """Asynchronous context manager for creating an OpenTelemetry span (no-op if disabled)."""
    global _tracer
    if _tracer is None:
        yield None
        return

    clean_attrs = sanitize_attributes(attributes or {})
    with _tracer.start_as_current_span(name, attributes=clean_attrs) as span:
        yield span
