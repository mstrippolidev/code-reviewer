"""
    SOLID2 out-of-scope fixture: Notifier depends on the NotificationChannel
    abstraction through constructor injection (satisfying DIP), but then
    uses isinstance to special-case one concrete subclass's behavior — this
    undermines the whole point of depending on the abstraction, but it is
    not itself an LSP override, an ISP-forced meaningless method, a
    concretely-constructed dependency, or a hard-to-substitute concrete
    dependency — a real DIP-adjacent smell outside the four in-scope
    categories.
"""
from abc import ABC, abstractmethod


class NotificationChannel(ABC):
    @abstractmethod
    def send(self, message: str) -> None: ...


class EmailChannel(NotificationChannel):
    def send(self, message: str) -> None:
        print(f"emailing: {message}")


class SmsChannel(NotificationChannel):
    def send(self, message: str) -> None:
        print(f"texting: {message}")


class Notifier:
    def __init__(self, channel: NotificationChannel) -> None:
        self._channel = channel

    def notify(self, message: str) -> None:
        if isinstance(self._channel, SmsChannel):
            message = message[:160]
        self._channel.send(message)
