"""
    COUP priority=high fixture: a visible cycle between two classes.
    Publisher holds a Subscriber and calls into it, and Subscriber holds
    the same Publisher back and calls into it, so neither can be read,
    changed, or tested alone.
"""


class Publisher:
    def __init__(self, name: str) -> None:
        self._name = name
        self._subscriber: "Subscriber | None" = None

    def register(self, subscriber: "Subscriber") -> None:
        self._subscriber = subscriber
        subscriber.set_publisher(self)

    def publish(self, message: str) -> None:
        self._subscriber.receive(message)


class Subscriber:
    def __init__(self) -> None:
        self._publisher: Publisher | None = None
        self._inbox: list[str] = []

    def set_publisher(self, publisher: Publisher) -> None:
        self._publisher = publisher

    def receive(self, message: str) -> None:
        self._inbox.append(message)

    def resend_last(self) -> None:
        self._publisher.publish(self._inbox[-1])
