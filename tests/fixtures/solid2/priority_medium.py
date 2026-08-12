"""
    SOLID2 priority=medium fixture: an ISP violation — the interface
    bundles two unrelated methods, forcing RobotWorker to define a
    meaningless implementation of eat().
"""
from abc import ABC, abstractmethod


class Worker(ABC):
    @abstractmethod
    def work(self) -> None: ...

    @abstractmethod
    def eat(self) -> None: ...


class RobotWorker(Worker):
    def work(self) -> None:
        print("welding")

    def eat(self) -> None:
        raise NotImplementedError("robots don't eat")
