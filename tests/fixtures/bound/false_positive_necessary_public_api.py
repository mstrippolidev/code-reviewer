"""
    BOUND false-positive fixture: Stack exposes several public methods,
    but every one of them is a core part of what a stack offers. Should
    NOT be flagged as an oversized surface — none of these could be
    removed or hidden without removing what the class is for.
"""


class Stack:
    def __init__(self) -> None:
        self._items: list[int] = []

    def push(self, value: int) -> None:
        self._items.append(value)

    def pop(self) -> int:
        return self._items.pop()

    def peek(self) -> int:
        return self._items[-1]

    def is_empty(self) -> bool:
        return not self._items

    def size(self) -> int:
        return len(self._items)
