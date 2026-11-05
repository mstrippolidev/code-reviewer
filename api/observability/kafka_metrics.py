"""
    Metric instruments for the Kafka pipeline, recorded through the OpenTelemetry API only.
"""
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Meter, Observation

HANDLER_DURATION_BUCKETS_SECONDS = [0.05, 0.25, 1, 5, 15, 60, 180, 600]

CONSUMER = "code_reviewer.consumer"
TOPIC = "code_reviewer.topic"
OUTCOME = "code_reviewer.outcome"
ERROR_TYPE = "code_reviewer.error_type"


class PublishOutcome(StrEnum):
    PUBLISHED = "published"
    FAILED = "failed"


class MessageOutcome(StrEnum):
    PROCESSED = "processed"
    PARSE_ERROR = "parse_error"


class KafkaMetrics:
    """Holds the Kafka instruments so callers record events, not raw numbers and labels."""

    def __init__(self, meter: Meter) -> None:
        self._producer_messages = meter.create_counter(
            "code_reviewer.kafka.producer.messages",
            unit="{message}",
            description="Messages published, by topic and outcome",
        )
        self._dlq_messages = meter.create_counter(
            "code_reviewer.kafka.dlq.messages", unit="{message}", description="Messages sent to a dead-letter topic"
        )
        self._consumer_messages = meter.create_counter(
            "code_reviewer.kafka.consumer.messages", unit="{message}", description="Messages consumed, by outcome"
        )
        self._handler_duration = meter.create_histogram(
            "code_reviewer.kafka.consumer.handler_duration",
            unit="s",
            description="Wall time a consumer spent on one message",
            explicit_bucket_boundaries_advisory=HANDLER_DURATION_BUCKETS_SECONDS,
        )
        self._consumer_crashes = meter.create_counter(
            "code_reviewer.kafka.consumer.crashes", unit="{crash}", description="Consumer loops that crashed"
        )
        self._consumer_lag: dict[tuple[str, str], int] = {}
        meter.create_observable_gauge(
            "code_reviewer.kafka.consumer.lag",
            callbacks=[self._observe_consumer_lag],
            unit="{message}",
            description="Messages published to a topic and not yet committed by a consumer",
        )

    def record_publish(self, topic: str, outcome: PublishOutcome) -> None:
        """Counts one message published, or one that could not be."""
        self._producer_messages.add(1, {TOPIC: topic, OUTCOME: outcome.value})

    def record_dlq_publish(self, dlq_topic: str, error_type: str, outcome: PublishOutcome) -> None:
        """Counts one message forwarded to a dead-letter topic, or one that could not be."""
        self._dlq_messages.add(1, {TOPIC: dlq_topic, ERROR_TYPE: error_type, OUTCOME: outcome.value})

    def record_message_consumed(self, consumer: str, topic: str, outcome: MessageOutcome) -> None:
        """Counts one message a consumer finished handling."""
        self._consumer_messages.add(1, {CONSUMER: consumer, TOPIC: topic, OUTCOME: outcome.value})

    @contextmanager
    def track_message_handling(self, consumer: str, topic: str) -> Iterator[None]:
        """Times the enclosed handling of one message, whether or not it fails."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self._handler_duration.record(time.perf_counter() - started, {CONSUMER: consumer, TOPIC: topic})

    def record_consumer_crash(self, consumer: str) -> None:
        """Counts one consumer loop that stopped on an unhandled error."""
        self._consumer_crashes.add(1, {CONSUMER: consumer})

    def record_consumer_lag(self, consumer: str, topic: str, lag: int) -> None:
        """Stores the latest lag the sampler measured for one consumer on one topic."""
        self._consumer_lag[(consumer, topic)] = lag

    def _observe_consumer_lag(self, options: CallbackOptions) -> Iterable[Observation]:
        for (consumer, topic), lag in list(self._consumer_lag.items()):
            yield Observation(lag, {CONSUMER: consumer, TOPIC: topic})


kafka_metrics = KafkaMetrics(metrics.get_meter("api"))
