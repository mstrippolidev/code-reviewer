"""
    Sends one clearly labelled mock dead letter through the real consumer into the real SNS topic.
    Opt-in: run with `pytest -m sns`. Every run emails the topic's subscriber.
"""
import pytest

from api.indexing.consumers.dlq_consumer import DlqConsumer
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.sns_dlq_notifier import SnsDlqNotifier

pytestmark = pytest.mark.sns

PORTFOLIO_TOPIC_ARN = "arn:aws:sns:us-east-1:413001138120:portfolioTopic"


class FakeDeadLetterRecord:
    topic = "review.requested.dlq"
    partition = 0
    offset = 0
    key = b"integration-test"
    value = b'{"review_id": "not-a-real-review"}'
    headers = [
        ("error_type", b"IntegrationTestMessage"),
        ("error_message", b"Mock dead letter from the DLQ SNS integration test. Safe to ignore."),
    ]


class FakeKafkaConsumer:
    async def commit(self) -> None:
        return None


class DeliveryTrackingNotifier(DlqNotifier):
    """Wraps the real notifier so the test can see delivery succeed, since the consumer swallows delivery errors."""

    def __init__(self, delivering_notifier: DlqNotifier) -> None:
        self._delivering_notifier = delivering_notifier
        self.delivered_count = 0

    def notify(self, subject: str, body: str) -> None:
        self._delivering_notifier.notify(subject, body)
        self.delivered_count += 1


@pytest.mark.asyncio
async def test_mock_dead_letter_is_delivered_to_the_real_sns_topic() -> None:
    """Verify a dead letter flows through the consumer and SNS accepts the publish with the instance's credentials."""
    notifier = DeliveryTrackingNotifier(SnsDlqNotifier.for_topic(PORTFOLIO_TOPIC_ARN))
    consumer = DlqConsumer(notifier)

    await consumer._process_message(FakeDeadLetterRecord(), FakeKafkaConsumer())

    assert notifier.delivered_count == 1
