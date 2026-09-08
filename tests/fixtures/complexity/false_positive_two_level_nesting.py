"""
    CMPLX false-positive fixture: exactly two levels of nesting (a loop
    containing one if). Should NOT be flagged by item 1 — the rule
    targets MORE than 2 levels deep; two is the boundary, not a
    violation of it.
"""


def count_matches(values: list[int], target: int) -> int:
    matches = 0
    for value in values:
        if value == target:
            matches += 1
    return matches
