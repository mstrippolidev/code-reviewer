"""
    Integration test for RepoIndexProducer against the real local Kafka
    cluster (kafka-dev namespace). Publishes to a dedicated test topic
    rather than the real repo.registered topic, so it never leaves messages
    behind for the real indexing consumer to pick up.
"""
import asyncio
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer

from api.config.settings import get_api_settings
from api.indexing.producer import RepoIndexProducer
from api.schemas.indexing import RepoRegisteredMessage

INTEGRATION_TEST_TOPIC = "repo.registered.integration-test"
CONSUME_TIMEOUT_SECONDS = 10


def _make_message() -> RepoRegisteredMessage:
    return RepoRegisteredMessage(
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        registered_by_user_id=1,
    )


@pytest.mark.kafka
@pytest.mark.asyncio
async def test_publish_repo_registered_is_readable_by_a_real_consumer() -> None:
    settings = get_api_settings()
    message = _make_message()
    producer = RepoIndexProducer(bootstrap_servers=settings.kafka_bootstrap_servers, topic=INTEGRATION_TEST_TOPIC)
    consumer = AIOKafkaConsumer(
        INTEGRATION_TEST_TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        group_id=f"repo-index-producer-integration-test-{uuid4()}",
    )

    await producer.start()
    await consumer.start()
    try:
        await producer.publish_repo_registered(message)
        record = await asyncio.wait_for(consumer.getone(), timeout=CONSUME_TIMEOUT_SECONDS)
    finally:
        await producer.stop()
        await consumer.stop()

    assert RepoRegisteredMessage.model_validate_json(record.value) == message


@pytest.mark.kafka
@pytest.mark.asyncio
async def test_publish_repo_registered_keys_the_record_by_repo_id() -> None:
    settings = get_api_settings()
    message = _make_message()
    producer = RepoIndexProducer(bootstrap_servers=settings.kafka_bootstrap_servers, topic=INTEGRATION_TEST_TOPIC)
    consumer = AIOKafkaConsumer(
        INTEGRATION_TEST_TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        group_id=f"repo-index-producer-integration-test-{uuid4()}",
    )

    await producer.start()
    await consumer.start()
    try:
        await producer.publish_repo_registered(message)
        record = await asyncio.wait_for(consumer.getone(), timeout=CONSUME_TIMEOUT_SECONDS)
    finally:
        await producer.stop()
        await consumer.stop()

    assert record.key == str(message.repo_id).encode()
