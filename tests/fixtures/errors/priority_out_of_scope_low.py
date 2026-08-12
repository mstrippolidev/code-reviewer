"""
    ERR out-of-scope fixture: a custom exception is raised (not a generic
    type, not swallowed, not dead code, not a sentinel return) but its
    message is uselessly vague — an error-handling-adjacent quality issue
    outside the four in-scope categories, so it must still be flagged, but
    only at priority low.
"""


class OrderError(Exception):
    pass


def validate_order(order: dict) -> None:
    if not order.get("items"):
        raise OrderError("bad")
