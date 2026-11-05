"""
    Interface for all consumers
"""
import logging
from abc import ABCMeta, abstractmethod
from typing import Generic, TypeVar

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from opentelemetry import propagate, trace
from opentelemetry.context import Context

from api.observability.kafka_lag import ConsumerLagSampler
from api.observability.kafka_metrics import MessageOutcome, kafka_metrics

ParsedMessage = TypeVar("ParsedMessage")

tracer = trace.get_tracer(__name__)


def _context_from_headers(msg: ConsumerRecord) -> Context:
    """Rebuilds the trace context the producer wrote into the message headers."""
    carrier = {key: value.decode() for key, value in msg.headers if value is not None}
    return propagate.extract(carrier)


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
        self._consumer_name = type(self).__name__
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
        lag_sampler = ConsumerLagSampler(self._consumer_name, consumer)
        lag_sampler.start()
        self._logger.info("Started consumer group_id=%s topic=%s", self.group_id, self.topic)
        try:
            async for msg in consumer:
                await self._process_message(msg, consumer)
        except Exception:
            kafka_metrics.record_consumer_crash(self._consumer_name)
            self._logger.exception("Consumer group_id=%s topic=%s crashed", self.group_id, self.topic)
            raise
        finally:
            await lag_sampler.stop()
            await consumer.stop()
            self._logger.info("Stopped consumer group_id=%s topic=%s", self.group_id, self.topic)

    async def _process_message(self, msg: ConsumerRecord, consumer: AIOKafkaConsumer) -> None:
        with tracer.start_as_current_span(
            f"{msg.topic} process", context=_context_from_headers(msg), kind=trace.SpanKind.CONSUMER
        ), kafka_metrics.track_message_handling(self._consumer_name, msg.topic):
            await self._handle_message(msg, consumer)

    async def _handle_message(self, msg: ConsumerRecord, consumer: AIOKafkaConsumer) -> None:
        try:
            parsed = self._parse_msg(msg)
        except Exception as error:
            kafka_metrics.record_message_consumed(self._consumer_name, msg.topic, MessageOutcome.PARSE_ERROR)
            await self._handle_parse_error(msg, error)
            await consumer.commit()
            return
        await self._handle_parsed_message(parsed, msg, consumer)
        await consumer.commit()
        kafka_metrics.record_message_consumed(self._consumer_name, msg.topic, MessageOutcome.PROCESSED)

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
