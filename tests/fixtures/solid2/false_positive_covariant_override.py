"""
    SOLID2 false-positive fixture: the override accepts a broader input
    type and returns a more specific one than the parent declares. Should
    NOT be flagged as an LSP violation — widening what a method accepts
    and narrowing what it returns honors the parent's contract; a caller
    that only knows the parent type is never surprised.
"""
from abc import ABC, abstractmethod


class AnimalShelter(ABC):
    @abstractmethod
    def admit(self, animal: "Dog") -> "Animal": ...


class Animal:
    pass


class Dog(Animal):
    pass


class Puppy(Dog):
    pass


class FlexibleShelter(AnimalShelter):
    def admit(self, animal: Animal) -> Puppy:
        return Puppy()
