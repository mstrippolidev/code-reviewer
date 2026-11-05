"""
    Tests that KafkaMetrics turns each event into the right instrument and labels.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.observability.kafka_metrics import KafkaMetrics, MessageOutcome, PublishOutcome
from tests.metric_points import (
    KAFKA_CONSUMER_CRASHES,
    KAFKA_CONSUMER_LAG,
    KAFKA_CONSUMER_MESSAGES,
    KAFKA_DLQ_MESSAGES,
    KAFKA_HANDLER_DURATION,
    KAFKA_PRODUCER_MESSAGES,
    point_with,
    points_for,
)

_CONSUMER = "code_reviewer.consumer"
_TOPIC = "code_reviewer.topic"
_OUTCOME = "code_reviewer.outcome"
_ERROR_TYPE = "code_reviewer.error_type"


def test_a_published_message_is_counted_per_topic_and_outcome(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify publishes and failed publishes land in separate series for the same topic."""
    isolated_kafka_metrics.record_publish("repo.file.index", PublishOutcome.PUBLISHED)
    isolated_kafka_metrics.record_publish("repo.file.index", PublishOutcome.FAILED)

    published = point_with(metric_reader, KAFKA_PRODUCER_MESSAGES, {_TOPIC: "repo.file.index", _OUTCOME: "published"})
    failed = point_with(metric_reader, KAFKA_PRODUCER_MESSAGES, {_TOPIC: "repo.file.index", _OUTCOME: "failed"})
    assert (published.value, failed.value) == (1, 1)


def test_a_dead_letter_is_counted_with_its_error_type(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the error type is a label, so a degraded review can be told from a parse error."""
    isolated_kafka_metrics.record_dlq_publish("review.requested.dlq", "PipelineDegradedError", PublishOutcome.PUBLISHED)

    point = point_with(
        metric_reader,
        KAFKA_DLQ_MESSAGES,
        {_TOPIC: "review.requested.dlq", _ERROR_TYPE: "PipelineDegradedError", _OUTCOME: "published"},
    )
    assert point.value == 1


def test_a_consumed_message_is_counted_per_consumer_topic_and_outcome(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify processed and unparseable messages are separate series."""
    isolated_kafka_metrics.record_message_consumed("ReviewRequestConsumer", "review.requested", MessageOutcome.PROCESSED)
    isolated_kafka_metrics.record_message_consumed("ReviewRequestConsumer", "review.requested", MessageOutcome.PARSE_ERROR)

    labels = {_CONSUMER: "ReviewRequestConsumer", _TOPIC: "review.requested"}
    assert point_with(metric_reader, KAFKA_CONSUMER_MESSAGES, {**labels, _OUTCOME: "processed"}).value == 1
    assert point_with(metric_reader, KAFKA_CONSUMER_MESSAGES, {**labels, _OUTCOME: "parse_error"}).value == 1


def test_handling_time_is_recorded_even_when_the_handler_raises(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a slow handler that fails is still timed, since that is the case worth seeing."""
    with pytest.raises(RuntimeError):
        with isolated_kafka_metrics.track_message_handling("ReviewRequestConsumer", "review.requested"):
            raise RuntimeError("boom")

    point = point_with(metric_reader, KAFKA_HANDLER_DURATION, {_CONSUMER: "ReviewRequestConsumer"})
    assert point.count == 1


def test_a_consumer_crash_is_counted(isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader) -> None:
    """Verify each crash of a consumer loop adds one."""
    isolated_kafka_metrics.record_consumer_crash("RepoIndexConsumer")

    assert point_with(metric_reader, KAFKA_CONSUMER_CRASHES, {_CONSUMER: "RepoIndexConsumer"}).value == 1


def test_consumer_lag_reports_the_latest_value_per_consumer_and_topic(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a newer measurement replaces the older one instead of adding to it."""
    isolated_kafka_metrics.record_consumer_lag("ReviewRequestConsumer", "review.requested", 12)
    isolated_kafka_metrics.record_consumer_lag("ReviewRequestConsumer", "review.requested", 3)

    point = point_with(metric_reader, KAFKA_CONSUMER_LAG, {_CONSUMER: "ReviewRequestConsumer"})
    assert point.value == 3


def test_consumer_lag_keeps_each_consumer_and_topic_apart(
    isolated_kafka_metrics: KafkaMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify two consumers, or two topics of one consumer, are separate series."""
    isolated_kafka_metrics.record_consumer_lag("DlqConsumer", "repo.registered.dlq", 1)
    isolated_kafka_metrics.record_consumer_lag("DlqConsumer", "review.requested.dlq", 2)

    assert len(points_for(metric_reader, KAFKA_CONSUMER_LAG)) == 2


def test_consumer_lag_reports_nothing_before_the_first_measurement(metric_reader: InMemoryMetricReader, isolated_kafka_metrics: KafkaMetrics) -> None:
    """Verify an unmeasured consumer produces no point rather than a misleading zero."""
    assert points_for(metric_reader, KAFKA_CONSUMER_LAG) == []
