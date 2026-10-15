import logging
from typing import Protocol

from pydantic import BaseModel

from api.db.models.registered_repo import RegisteredRepo
from api.indexing.producer import PublishError
from api.indexing.topics import REPO_FILE_RETRY, REPO_REGISTERED, REPO_STATUS_PROGRESS
from api.repos.errors import RepoEventPublishError
from api.schemas.indexing import RepoRegisteredMessage
from api.schemas.repos import RepoStatusProgressMessage

logger = logging.getLogger(__name__)

REGISTRATION_FAILURE_MESSAGE = "Could not queue this repo for indexing"
RETRY_FAILURE_MESSAGE = "Could not schedule a retry of this repo's failed files"


class MessageProducer(Protocol):
    """Contract for anything that can publish a keyed message to a topic."""

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None: ...


class RepoEventPublisher:
    """Publishes a registered repo's lifecycle events to the indexing pipeline's topics."""

    def __init__(self, producer: MessageProducer) -> None:
        self._producer = producer

    async def publish_registered(self, repo: RegisteredRepo) -> None:
        await self._publish_or_raise(REPO_REGISTERED, self._registration_message(repo), REGISTRATION_FAILURE_MESSAGE)

    async def publish_file_retry(self, repo: RegisteredRepo) -> None:
        await self._publish_or_raise(REPO_FILE_RETRY, self._registration_message(repo), RETRY_FAILURE_MESSAGE)

    async def publish_status_progress(self, repo: RegisteredRepo) -> None:
        message = RepoStatusProgressMessage.from_registered_repo(repo)
        try:
            await self._producer.publish(REPO_STATUS_PROGRESS, message, str(repo.repo_id).encode())
        except Exception:
            # A lost notification, not a lost result — repo.status above is already committed.
            logger.exception("Failed to publish repo.status.progress for repo_id=%s", repo.repo_id)

    async def _publish_or_raise(self, topic: str, message: RepoRegisteredMessage, failure_message: str) -> None:
        try:
            await self._producer.publish(topic, message, str(message.repo_id).encode())
        except PublishError as error:
            raise RepoEventPublishError(failure_message) from error

    def _registration_message(self, repo: RegisteredRepo) -> RepoRegisteredMessage:
        return RepoRegisteredMessage(
            repo_id=repo.repo_id,
            owner_id=repo.owner_id,
            full_name=repo.full_name,
            branch=repo.branch,
            registered_by_user_id=repo.registered_by_user_id,
        )
