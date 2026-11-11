"""
    COUP gray-area fixture: a value class that reads another instance's
    underscore attribute inside __eq__ and __add__. The prompt flags reaching
    into a private attribute of another class, and here the other object is the
    same class.
"""


class Money:
    def __init__(self, cents: int) -> None:
        self._cents = cents

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Money) and self._cents == other._cents

    def __add__(self, other: "Money") -> "Money":
        return Money(self._cents + other._cents)

    def display(self) -> str:
        return f"{self._cents / 100:.2f}"
