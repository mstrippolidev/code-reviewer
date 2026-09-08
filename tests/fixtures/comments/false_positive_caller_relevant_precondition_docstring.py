"""
    CMT false-positive fixture: the docstring names an algorithm choice
    only to state a precondition the caller must honor. Should NOT be
    flagged as leaking implementation reasoning — item 4 targets internal
    reasoning about HOW the author got there; a precondition the caller
    must satisfy is part of the public contract, not implementation detail.
"""


def find_index(sorted_values: list[int], target: int) -> int:
    """Binary-search sorted_values for target. Callers must pass values
    already sorted ascending; behavior is undefined otherwise.
    """
    low, high = 0, len(sorted_values) - 1
    while low <= high:
        mid = (low + high) // 2
        if sorted_values[mid] == target:
            return mid
        if sorted_values[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
