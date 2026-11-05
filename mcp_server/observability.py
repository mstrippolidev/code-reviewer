"""
    OpenTelemetry SDK setup for the MCP server process.
"""
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from mcp_server.config import McpSettings

SERVICE_NAME = "code-reviewer-mcp"


def configure_telemetry(settings: McpSettings) -> None:
    """Exports the MCP library's own spans and metrics, and traces the calls to api/, passing the trace on to it."""
    _configure_tracing(settings)
    _configure_metrics(settings)
    HTTPXClientInstrumentor().instrument()


def _configure_tracing(settings: McpSettings) -> None:
    """Registers the global tracer provider that exports spans over OTLP."""
    provider = TracerProvider(resource=_build_resource())
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _configure_metrics(settings: McpSettings) -> None:
    """Registers the global meter provider that pushes metrics to the Collector."""
    exporter = OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_metrics_endpoint)
    reader = PeriodicExportingMetricReader(
        exporter, export_interval_millis=settings.otel_metric_export_interval_ms
    )
    metrics.set_meter_provider(MeterProvider(resource=_build_resource(), metric_readers=[reader]))


def _build_resource() -> Resource:
    """Names this process on every span and metric it exports."""
    return Resource.create({"service.name": SERVICE_NAME})
