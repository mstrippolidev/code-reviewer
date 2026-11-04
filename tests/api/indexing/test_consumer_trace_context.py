"""
    ConsumerInterface continues the trace a producer started, using the context in the message headers.
"""
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from api.indexing.consumers import interface
from api.indexing.consumers.interface import ConsumerInterface

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
PRODUCER_SPAN_ID = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE_ID}-{PRODUCER_SPAN_ID}-01"
TOPIC = "review.requested"


class FakeConsumerRecord:
    def __init__(self, headers: list[tuple[str, bytes]]) -> None:
        self.topic = TOPIC
        self.headers = headers
        self.value = b""
        self.offset = 0


class FakeKafkaConsumer:
    async def commit(self) -> None:
        pass


class RecordingConsumer(ConsumerInterface[bytes]):
    def __init__(self) -> None:
        super().__init__(TOPIC, "unused")
        self.span_id_while_handling: int | None = None

    def _parse_msg(self, msg: FakeConsumerRecord) -> bytes:
        return msg.value

    async def _handle_parse_error(self, msg: FakeConsumerRecord, error: Exception) -> None:
        raise error

    async def _handle_parsed_message(
        self, parsed: bytes, msg: FakeConsumerRecord, consumer: FakeKafkaConsumer
    ) -> None:
        self.span_id_while_handling = trace.get_current_span().get_span_context().span_id


@pytest.fixture
def exported_spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(interface, "tracer", provider.get_tracer("test"))
    return exporter


@pytest.mark.asyncio
async def test_processing_span_continues_the_trace_in_the_message_headers(
    exported_spans: InMemorySpanExporter,
) -> None:
    consumer = RecordingConsumer()
    record = FakeConsumerRecord(headers=[("traceparent", TRACEPARENT.encode())])

    await consumer._process_message(record, FakeKafkaConsumer())

    (span,) = exported_spans.get_finished_spans()
    assert span.name == f"{TOPIC} process"
    assert span.kind == trace.SpanKind.CONSUMER
    assert span.context.trace_id == int(TRACE_ID, 16)
    assert span.parent.span_id == int(PRODUCER_SPAN_ID, 16)


@pytest.mark.asyncio
async def test_handler_runs_inside_the_processing_span(exported_spans: InMemorySpanExporter) -> None:
    consumer = RecordingConsumer()
    record = FakeConsumerRecord(headers=[("traceparent", TRACEPARENT.encode())])

    await consumer._process_message(record, FakeKafkaConsumer())

    (span,) = exported_spans.get_finished_spans()
    assert consumer.span_id_while_handling == span.context.span_id


@pytest.mark.asyncio
async def test_message_without_trace_headers_starts_a_new_trace(exported_spans: InMemorySpanExporter) -> None:
    consumer = RecordingConsumer()

    await consumer._process_message(FakeConsumerRecord(headers=[]), FakeKafkaConsumer())

    (span,) = exported_spans.get_finished_spans()
    assert span.parent is None
