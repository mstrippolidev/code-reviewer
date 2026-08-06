"""
    LSP violation fixture: a subclass raises on a method its parent
    contract guarantees behaves normally, breaking substitutability for
    any caller that only knows the parent type.
"""
from abc import ABC, abstractmethod


class Bird(ABC):
    """Abstraction for a bird that can move around."""

    @abstractmethod
    def fly(self, meters: int) -> None:
        """Move the bird forward by meters, airborne."""


class Sparrow(Bird):
    def fly(self, meters: int) -> None:
        print(f"Flying {meters} meters")


class Penguin(Bird):
    def fly(self, meters: int) -> None:
        raise NotImplementedError("Penguins cannot fly")
