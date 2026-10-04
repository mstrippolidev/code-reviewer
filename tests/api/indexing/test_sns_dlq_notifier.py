"""
    Tests for SnsDlqNotifier against a fake SNS client: no AWS calls.
"""
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from api.indexing.consumers.sns_dlq_notifier import DlqNotificationDeliveryError, SnsDlqNotifier

TOPIC_ARN = "arn:aws:sns:us-east-1:413001138120:portfolioTopic"


class FakeSnsClient:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[dict[str, str]] = []

    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> dict:
        if self._publish_error:
            raise self._publish_error
        self.published.append({"TopicArn": TopicArn, "Subject": Subject, "Message": Message})
        return {"MessageId": "fake-id"}


def test_notify_publishes_to_the_configured_topic() -> None:
    """Verify the notification goes to the topic the notifier was built for."""
    client = FakeSnsClient()
    notifier = SnsDlqNotifier(TOPIC_ARN, client)

    notifier.notify("review.requested.dlq: RuntimeError", "body text")

    assert client.published[0]["TopicArn"] == TOPIC_ARN


def test_notify_sends_the_body_as_the_message() -> None:
    """Verify the body reaches the subscriber unchanged."""
    client = FakeSnsClient()
    notifier = SnsDlqNotifier(TOPIC_ARN, client)

    notifier.notify("subject", "topic: x\noffset: 4")

    assert client.published[0]["Message"] == "topic: x\noffset: 4"


def test_notify_truncates_subject_to_the_sns_limit() -> None:
    """Verify an overlong subject is cut to 100 characters, which SNS would otherwise reject."""
    client = FakeSnsClient()
    notifier = SnsDlqNotifier(TOPIC_ARN, client)

    notifier.notify("x" * 250, "body")

    assert len(client.published[0]["Subject"]) == 100


def test_notify_collapses_newlines_in_the_subject() -> None:
    """Verify a multi-line subject becomes one line, since SNS rejects line breaks in subjects."""
    client = FakeSnsClient()
    notifier = SnsDlqNotifier(TOPIC_ARN, client)

    notifier.notify("first line\nsecond line", "body")

    assert client.published[0]["Subject"] == "first line second line"


def test_notify_wraps_an_sns_rejection_in_a_delivery_error() -> None:
    """Verify an SNS API error surfaces as a domain exception, not a botocore one."""
    rejection = ClientError({"Error": {"Code": "AuthorizationError", "Message": "denied"}}, "Publish")
    notifier = SnsDlqNotifier(TOPIC_ARN, FakeSnsClient(publish_error=rejection))

    with pytest.raises(DlqNotificationDeliveryError):
        notifier.notify("subject", "body")


def test_notify_wraps_an_unreachable_endpoint_in_a_delivery_error() -> None:
    """Verify a network failure to SNS surfaces as the same domain exception."""
    unreachable = EndpointConnectionError(endpoint_url="https://sns.us-east-1.amazonaws.com")
    notifier = SnsDlqNotifier(TOPIC_ARN, FakeSnsClient(publish_error=unreachable))

    with pytest.raises(DlqNotificationDeliveryError):
        notifier.notify("subject", "body")


def test_for_topic_builds_a_client_in_the_topics_own_region() -> None:
    """Verify the client targets the topic's region (us-east-1), not the deployment's region."""
    notifier = SnsDlqNotifier.for_topic(TOPIC_ARN)

    assert notifier._client.meta.region_name == "us-east-1"
