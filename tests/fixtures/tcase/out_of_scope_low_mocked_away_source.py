"""
    TCASE out-of-scope fixture, deliberately distinct from the worked
    example now in the prompt (vacuous assertions): total_with_tax has
    one real path, fully exercised by its paired test, but the test
    replaces calculate_tax with a stub and only checks that it was
    called — the actual arithmetic this function is responsible for is
    never verified against a real value, a different kind of "left
    unverified" than a vacuous assertion or an unreached path.
"""


def calculate_tax(subtotal: float) -> float:
    return subtotal * 0.08


def total_with_tax(subtotal: float) -> float:
    return subtotal + calculate_tax(subtotal)
