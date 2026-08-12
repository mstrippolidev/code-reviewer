"""
    ERR priority=high fixture: an exception is swallowed on a path callers
    are likely to rely on — a message queue handler that silently drops
    processing failures instead of surfacing them.
"""


def process_queue_message(message: dict) -> None:
    try:
        _handle_message(message)
    except Exception:
        pass


def _handle_message(message: dict) -> None:
    print(f"handling {message['id']}")
