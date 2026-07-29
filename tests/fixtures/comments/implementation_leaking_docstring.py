"""
    Comment fixture: a docstring that explains internal implementation
    reasoning instead of describing the function's public contract.
"""


def merge_settings(base: dict, overrides: dict) -> dict:
    """
    We use a shallow dict copy here instead of deepcopy because profiling
    showed deepcopy was too slow for large settings dicts during the 2025
    migration, and a shallow copy is safe since values are never mutated
    in place elsewhere in the codebase.
    """
    merged = base.copy()
    merged.update(overrides)
    return merged
