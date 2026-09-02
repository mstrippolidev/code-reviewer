class CustomerName:
    """Holds a customer's display name."""

    def __init__(self, value: str) -> None:
        self._value = value

    def value(self) -> str:
        return self._value
