"""
    TCASE priority=low fixture: a trivial, single-expression helper — the
    paired test covers the normal case, leaving only the obvious zero
    boundary untested.
"""


def clamp_to_positive(value: int) -> int:
    return max(value, 0)
