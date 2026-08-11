"""
    Naming fixture: a comprehension loop variable using the singular form
    of the plural parameter it iterates over. Not the same identifier as
    the parameter, so this is not shadowing — and shadowing itself isn't
    one of this agent's four naming-clarity criteria regardless.
"""


def filter_active_subscribers(subscribers: list[dict]) -> list[dict]:
    """Return only subscribers whose subscription is currently active."""
    return [subscriber for subscriber in subscribers if subscriber["is_active"]]
