"""
    Hands the messages of finished agent runs to a caller that asked for them.
"""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.messages import BaseMessage

_open_transcript: ContextVar[list[BaseMessage] | None] = ContextVar("open_transcript", default=None)


@contextmanager
def capture_transcript() -> Iterator[list[BaseMessage]]:
    """Collects the messages of every agent run finished inside the block, in order."""
    messages: list[BaseMessage] = []
    token = _open_transcript.set(messages)
    try:
        yield messages
    finally:
        _open_transcript.reset(token)


def record_transcript(messages: Sequence[BaseMessage]) -> None:
    """Adds a finished run's messages to the open capture; does nothing when none is open."""
    transcript = _open_transcript.get()
    if transcript is not None:
        transcript.extend(messages)
