"""
    Consumes repo.registered.dlq: notifies a human per message, no retry, no reprocessing.
"""
import logging
from collections.abc import Sequence

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError

from api.config.settings import get_api_settings
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.topics import REPO_REGISTERED_DLQ
from api.schemas.indexing import RepoRegisteredMessage

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = "repo_index_dlq_consumer"
TOPIC = REPO_REGISTERED_DLQ
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoIndexDlqConsumer(ConsumerInterface[tuple[str, str, str]]):
    """Sends one notification per message that lands on repo.registered.dlq."""

    def __init__(self, notifier: DlqNotifier, topic: str = TOPIC,
                 bootstrap_servers: str = BOOTSTRAP_SERVER, group_id: str = GROUP_ID) -> None:
        super().__init__(topic, bootstrap_servers, group_id, enable_auto_commit=False)
        self._notifier = notifier

    def _parse_msg(self, msg: ConsumerRecord) -> tuple[str, str, str]:
        repo_id = _read_repo_id(msg.value)
        error_type, error_message = _read_error_headers(msg.headers)
        return repo_id, error_type, error_message

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not interpret repo.registered.dlq message at offset=%s", msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, parsed: tuple[str, str, str], msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        repo_id, error_type, error_message = parsed
        try:
            self._notifier.notify(
                subject=f"repo.registered.dlq: repo_id={repo_id} ({error_type})",
                body=f"repo_id: {repo_id}\nerror_type: {error_type}\nerror_message: {error_message}",
            )
        except Exception as error:
            logger.error("Failed to send DLQ notification for offset=%s", msg.offset, exc_info=error)


def _read_repo_id(payload: bytes) -> str:
    try:
        return str(RepoRegisteredMessage.model_validate_json(payload).repo_id)
    except ValidationError:
        return "unknown"


def _read_error_headers(headers: Sequence[tuple[str, bytes]]) -> tuple[str, str]:
    header_values = dict(headers)
    error_type = header_values.get("error_type", b"UnknownError").decode()
    error_message = header_values.get("error_message", b"").decode()
    return error_type, error_message
