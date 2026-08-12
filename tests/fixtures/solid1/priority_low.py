"""
    SOLID1 priority=low fixture: four parameters, just past the threshold,
    confined to a tiny debug-only helper with limited reach.
"""


def _debug_format_record(a: str, b: str, c: str, d: str) -> str:
    """Debug-only formatter, never called from a production code path."""
    return f"{a}-{b}-{c}-{d}"
