"""
    Notification sink for repo.registered.dlq — the concrete implementation
    is a per-deployment choice (AWS SNS, email, Slack, ...), never hardcoded here.
"""
from abc import ABC, abstractmethod


class DlqNotifier(ABC):
    """One notification about a message that landed on the DLQ."""

    @abstractmethod
    def notify(self, subject: str, body: str) -> None:
        """Raises: whatever the concrete sink raises on delivery failure."""


class PrintDlqNotifier(DlqNotifier):
    """Default notifier: prints to stdout. Replace with a real sink before running against a live DLQ."""

    def notify(self, subject: str, body: str) -> None:
        print(f"{subject}\n{body}")
