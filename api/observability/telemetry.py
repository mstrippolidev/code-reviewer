"""
    OpenTelemetry SDK setup for the API process.
"""
from fastapi import FastAPI
from openinference.instrumentation import TraceConfig
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.config.settings import ApiSettings

SERVICE_NAME = "code-reviewer-api"
_UNTRACED_URLS = "health,/api/reviews/[0-9a-f-]{36}$,/api/oauth/github/me"


def configure_telemetry(settings: ApiSettings) -> TracerProvider:
    """Registers the global tracer provider and starts the instrumentors that need no app object."""
    provider = TracerProvider(resource=_build_resource())
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    AIOKafkaInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    hide_payloads = not settings.otel_capture_payloads
    LangChainInstrumentor().instrument(
        tracer_provider=provider,
        config=TraceConfig(hide_inputs=hide_payloads, hide_outputs=hide_payloads),
    )
    LoggingInstrumentor().instrument(inject_trace_context=True)
    return provider


def configure_metrics(settings: ApiSettings) -> MeterProvider:
    """Registers the global meter provider that pushes metrics to the Collector."""
    exporter = OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_metrics_endpoint)
    reader = PeriodicExportingMetricReader(
        exporter, export_interval_millis=settings.otel_metric_export_interval_ms
    )
    provider = MeterProvider(resource=_build_resource(), metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def instrument_fastapi(app: FastAPI) -> None:
    """Adds one span per request to the app, skipping the health check and the polling routes."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls=_UNTRACED_URLS, exclude_spans=["receive", "send"])


def _build_resource() -> Resource:
    """Names this process on every span and metric it exports."""
    return Resource.create({"service.name": SERVICE_NAME})
