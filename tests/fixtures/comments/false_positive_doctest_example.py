"""
    CMT false-positive fixture: a doctest-style usage example inside a
    docstring. Should NOT be flagged as commented-out code left in place
    — item 3 targets dead code accidentally left behind, not a
    deliberate, runnable usage example documenting the contract.
"""


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces.

    >>> normalize_whitespace("a   b\\tc")
    'a b c'
    """
    return " ".join(text.split())
