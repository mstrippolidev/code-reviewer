"""
    OpenTelemetry SDK setup for the MCP server process.
"""
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from mcp_server.config import McpSettings

SERVICE_NAME = "code-reviewer-mcp"


def configure_telemetry(settings: McpSettings) -> None:
    """Exports the MCP library's own spans and traces the calls to api/, passing the trace on to it."""
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
