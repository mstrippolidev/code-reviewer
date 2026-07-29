"""
    Error handling fixture: returns a sentinel error code instead of
    raising when the input is invalid, pushing the check onto every caller.
"""


def parse_age(raw: str) -> int:
    if not raw.isdigit():
        return -1
    return int(raw)
