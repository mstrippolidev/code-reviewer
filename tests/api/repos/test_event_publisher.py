"""
    Tests for RepoEventPublisher against a fake producer: no real Kafka.
"""
from datetime import datetime

import pytest
from pydantic import BaseModel

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.indexing.producer import PublishError
from api.indexing.topics import REPO_FILE_RETRY, REPO_REGISTERED, REPO_STATUS_PROGRESS
from api.repos.errors import RepoEventPublishError
from api.repos.event_publisher import RepoEventPublisher
from api.schemas.indexing import RepoRegisteredMessage
from api.schemas.repos import RepoStatusProgressMessage


class FakeProducer:
    def __init__(self, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.attempts = 0
        self.published: list[tuple[str, BaseModel, bytes]] = []

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None:
        self.attempts += 1
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "branch": "dev",
        "registered_by_user_id": 7,
        "status": RepoIndexStatus.INDEXING,
        "status_reason": None,
        "total_files_expected": 12,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


@pytest.mark.asyncio
async def test_publish_registered_sends_to_the_registered_topic() -> None:
    """Verify that a registration event lands on the topic the indexing consumer reads."""
    producer = FakeProducer()
    publisher = RepoEventPublisher(producer)

    await publisher.publish_registered(_make_registered_repo())

    assert producer.published[0][0] == REPO_REGISTERED


@pytest.mark.asyncio
async def test_publish_registered_carries_the_repos_registration_details() -> None:
    """Verify that the message uses the tracked branch, not the default branch."""
    producer = FakeProducer()
    publisher = RepoEventPublisher(producer)

    await publisher.publish_registered(_make_registered_repo())

    assert producer.published[0][1] == RepoRegisteredMessage(
        repo_id=10, owner_id=99, full_name="octocat/hello-world", branch="dev", registered_by_user_id=7
    )


@pytest.mark.asyncio
async def test_publish_registered_keys_the_message_by_repo_id() -> None:
    """Verify the key so every event for one repo lands on the same partition, in order."""
    producer = FakeProducer()
    publisher = RepoEventPublisher(producer)

    await publisher.publish_registered(_make_registered_repo(repo_id=10))

    assert producer.published[0][2] == b"10"


@pytest.mark.asyncio
async def test_publish_registered_reports_a_queue_failure_to_the_caller() -> None:
    """Verify that a Kafka failure on registration is raised with a client-safe message.

    The registration is unusable if it was never queued, so the caller must learn of it.
    """
    publisher = RepoEventPublisher(FakeProducer(publish_error=PublishError("broker down")))

    with pytest.raises(RepoEventPublishError, match="Could not queue this repo for indexing"):
        await publisher.publish_registered(_make_registered_repo())


@pytest.mark.asyncio
async def test_publish_registered_does_not_wrap_unexpected_errors() -> None:
    """Verify that only PublishError is translated; a programming error must stay visible."""
    publisher = RepoEventPublisher(FakeProducer(publish_error=RuntimeError("bug")))

    with pytest.raises(RuntimeError):
        await publisher.publish_registered(_make_registered_repo())


@pytest.mark.asyncio
async def test_publish_file_retry_sends_to_the_retry_topic() -> None:
    """Verify that a retry request reaches the consumer that re-indexes failed files."""
    producer = FakeProducer()
    publisher = RepoEventPublisher(producer)

    await publisher.publish_file_retry(_make_registered_repo())

    assert producer.published[0][0] == REPO_FILE_RETRY


@pytest.mark.asyncio
async def test_publish_file_retry_reports_a_queue_failure_with_its_own_message() -> None:
    """Verify that a failed retry is not described as a failed registration."""
    publisher = RepoEventPublisher(FakeProducer(publish_error=PublishError("broker down")))

    with pytest.raises(RepoEventPublishError, match="Could not schedule a retry"):
        await publisher.publish_file_retry(_make_registered_repo())


@pytest.mark.asyncio
async def test_publish_status_progress_sends_the_repos_current_status() -> None:
    """Verify that the progress event mirrors the repo's status, reason and expected file count."""
    producer = FakeProducer()
    publisher = RepoEventPublisher(producer)

    await publisher.publish_status_progress(_make_registered_repo())

    assert producer.published[0] == (
        REPO_STATUS_PROGRESS,
        RepoStatusProgressMessage(
            repo_id=10, status=RepoIndexStatus.INDEXING, status_reason=None, total_files_expected=12
        ),
        b"10",
    )


@pytest.mark.asyncio
async def test_publish_status_progress_swallows_a_failure_after_attempting_it() -> None:
    """Verify that a lost progress notification never fails the request.

    The status change is already committed; only the live update is lost.
    """
    producer = FakeProducer(publish_error=RuntimeError("broker down"))
    publisher = RepoEventPublisher(producer)

    await publisher.publish_status_progress(_make_registered_repo())

    assert producer.attempts == 1
