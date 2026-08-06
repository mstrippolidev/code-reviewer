"""
    ISP violation fixture: a single interface bundles unrelated
    capabilities, forcing an implementer that only needs one of them to
    define meaningless stubs for the rest.
"""
from abc import ABC, abstractmethod


class Worker(ABC):
    """Bundles unrelated responsibilities: working, eating, and sleeping."""

    @abstractmethod
    def work(self) -> None:
        """Perform the worker's job."""

    @abstractmethod
    def eat(self) -> None:
        """Consume a meal during a break."""

    @abstractmethod
    def sleep(self) -> None:
        """Rest between shifts."""


class RobotWorker(Worker):
    def work(self) -> None:
        print("Welding car parts")

    def eat(self) -> None:
        pass

    def sleep(self) -> None:
        pass
