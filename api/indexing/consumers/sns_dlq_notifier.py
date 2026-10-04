"""
    Delivers DLQ notifications to an AWS SNS topic.
"""
import logging
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from api.indexing.consumers.dlq_notifier import DlqNotifier

logger = logging.getLogger(__name__)

_MAX_SUBJECT_LENGTH = 100
_TOPIC_ARN_REGION_INDEX = 3


class DlqNotificationDeliveryError(Exception):
    """Raised when SNS rejects or cannot be reached for a DLQ notification."""


class SnsPublisher(Protocol):
    """The slice of the boto3 SNS client this notifier depends on."""

    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> dict: ...


class SnsDlqNotifier(DlqNotifier):
    """Publishes each DLQ notification to one SNS topic."""

    def __init__(self, topic_arn: str, client: SnsPublisher) -> None:
        self._topic_arn = topic_arn
        self._client = client

    @classmethod
    def for_topic(cls, topic_arn: str) -> "SnsDlqNotifier":
        """Builds the client in the topic's own region, which may differ from the deployment's."""
        region = topic_arn.split(":")[_TOPIC_ARN_REGION_INDEX]
        return cls(topic_arn, boto3.client("sns", region_name=region))

    def notify(self, subject: str, body: str) -> None:
        try:
            self._client.publish(TopicArn=self._topic_arn, Subject=_to_sns_subject(subject), Message=body)
        except (BotoCoreError, ClientError) as error:
            logger.error("SNS publish failed topic_arn=%s", self._topic_arn, exc_info=error)
            raise DlqNotificationDeliveryError(f"Could not publish DLQ notification to {self._topic_arn}") from error


def _to_sns_subject(subject: str) -> str:
    single_line_subject = " ".join(subject.split())
    return single_line_subject[:_MAX_SUBJECT_LENGTH]
