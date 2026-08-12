"""
    CMPLX out-of-scope fixture: control flow implemented via a raised and
    caught exception instead of an ordinary loop/return, which is not deep
    nesting, not a long boolean, not more than 3 exit points, and not high
    branch-count cyclomatic complexity — a real clarity problem outside
    the four in-scope categories, so it must still be flagged, but only at
    priority low.
"""


class _FoundNegative(Exception):
    def __init__(self, value: int) -> None:
        self.value = value


def find_first_negative(numbers: list[int]) -> int:
    try:
        for number in numbers:
            if number < 0:
                raise _FoundNegative(number)
        return -1
    except _FoundNegative as found:
        return found.value
