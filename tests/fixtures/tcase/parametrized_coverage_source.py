"""
    TCASE false-positive fixture: three branches, all exercised by one
    parametrized test in the paired test file. Should NOT be flagged for
    a coverage gap just because there is a single test function — what
    matters is which paths the test cases actually exercise, not how many
    test functions there are.
"""


def shipping_cost(weight_kg: float) -> float:
    if weight_kg <= 1:
        return 5.0
    if weight_kg <= 5:
        return 10.0
    return 20.0
