"""
    Consumers
"""
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.factory import FactoryConsumer
from api.indexing.consumers.repo_index_consumer import RepoIndexConsumerDependencies

async def consume(key: str, dependencies: RepoIndexConsumerDependencies | DlqNotifier) -> None:
    consumer = FactoryConsumer.create_consumer(key, dependencies)
    await consumer.consume()