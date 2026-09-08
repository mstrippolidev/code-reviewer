"""
    ERR false-positive fixture: returning early on an empty batch is a
    legitimate no-op, not a failure signal. Should NOT be flagged by item
    1 — an empty list of items to charge means there is nothing to do,
    not that charge_all failed.
"""


def charge_all(amounts_cents: list[int]) -> int:
    if not amounts_cents:
        return 0

    return sum(amounts_cents)
