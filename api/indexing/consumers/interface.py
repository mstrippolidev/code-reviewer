"""
    Interface for all consumers
"""
from abc import ABCMeta, abstractmethod
from aiokafka import AIOKafkaConsumer

class ConsumerInterface(metaclass=ABCMeta):
    """
        Interface for all consumers
    """
    def __init__(self, topic:str, bootstrap_servers:str, group_id: None | str = None,**kwargs) -> None:
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        self.auto_offset_reset = kwargs.get("auto_offset_reset", "earliest")
        self.enable_auto_commit = kwargs.get("enable_auto_commit", True)
        self.group_id = group_id

    def _build(self) -> AIOKafkaConsumer:
        """
            Build the consumer base on the settings
        """
        return AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=self.enable_auto_commit,
            auto_offset_reset=self.auto_offset_reset
        )

    @abstractmethod
    async def consume(self) -> None:
        """
            Abstract method to apply custom logic for consumers.
        """