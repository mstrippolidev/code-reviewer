"""
    Consumers
"""
from api.indexing.consumers.factory import ConsumerDependencies, FactoryConsumer

async def consume(key: str, dependencies: ConsumerDependencies) -> None:
    consumer = FactoryConsumer.create_consumer(key, dependencies)
    await consumer.consume()