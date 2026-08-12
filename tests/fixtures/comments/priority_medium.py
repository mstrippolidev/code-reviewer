"""
    CMT priority=medium fixture: a docstring that leaks internal
    implementation reasoning instead of describing the function's public
    contract.
"""


def deduplicate_ids(ids: list[str]) -> list[str]:
    """We use a set here instead of a list comprehension because in our
    2019 benchmark a set-based approach was roughly 3x faster on inputs
    over 10k items, which is why this looks different from the naive
    version you might expect."""
    return list(set(ids))
