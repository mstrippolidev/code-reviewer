"""
    Interface for all consumers
"""
import logging
from abc import ABCMeta, abstractmethod
from typing import Generic, TypeVar

from aiokafka import AIOKafkaConsumer, ConsumerRecord

ParsedMessage = TypeVar("ParsedMessage")


class ConsumerInterface(Generic[ParsedMessage], metaclass=ABCMeta):
    """
        Interface for all consumers
    """
    def __init__(self, topic: str | tuple[str, ...], bootstrap_servers: str, group_id: None | str = None, **kwargs) -> None:
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        self.auto_offset_reset = kwargs.get("auto_offset_reset", "earliest")
        self.enable_auto_commit = kwargs.get("enable_auto_commit", True)
        self.group_id = group_id
        self._logger = logging.getLogger(type(self).__module__)

    def _build(self) -> AIOKafkaConsumer:
        """
            Build the consumer base on the settings
        """
        topics = (self.topic,) if isinstance(self.topic, str) else self.topic
        return AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=self.enable_auto_commit,
            auto_offset_reset=self.auto_offset_reset
        )

    async def consume(self) -> None:
        """
            Start/iterate/stop loop shared by every consumer.
        """
        consumer = self._build()
        await consumer.start()
        self._logger.info("Started consumer group_id=%s topic=%s", self.group_id, self.topic)
        try:
            async for msg in consumer:
                await self._process_message(msg, consumer)
        except Exception:
            self._logger.exception("Consumer group_id=%s topic=%s crashed", self.group_id, self.topic)
            raise
        finally:
            await consumer.stop()
            self._logger.info("Stopped consumer group_id=%s topic=%s", self.group_id, self.topic)

    async def _process_message(self, msg: ConsumerRecord, consumer: AIOKafkaConsumer) -> None:
        try:
            parsed = self._parse_msg(msg)
        except Exception as error:
            await self._handle_parse_error(msg, error)
            await consumer.commit()
            return
        await self._handle_parsed_message(parsed, msg, consumer)
        await consumer.commit()

    @abstractmethod
    def _parse_msg(self, msg: ConsumerRecord) -> ParsedMessage:
        """
            Parse a raw Kafka message into this consumer's domain type, or raise.
        """

    @abstractmethod
    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        """
            Handle a message that failed to parse.
        """

    @abstractmethod
    async def _handle_parsed_message(self, parsed: ParsedMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer) -> None:
        """
            Handle a successfully parsed message.
        """
