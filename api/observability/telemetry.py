"""
    OpenTelemetry SDK setup for the API process.
"""
from fastapi import FastAPI
from openinference.instrumentation import TraceConfig
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.config.settings import ApiSettings

SERVICE_NAME = "code-reviewer-api"


def configure_telemetry(settings: ApiSettings) -> TracerProvider:
    """Registers the global tracer provider and starts the instrumentors that need no app object."""
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
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


def instrument_fastapi(app: FastAPI) -> None:
    """Adds one span per request to the app, skipping the health check."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health", exclude_spans=["receive", "send"])
