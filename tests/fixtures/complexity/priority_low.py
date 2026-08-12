"""
    CMPLX priority=low fixture: three levels of nesting, past the 2-level
    threshold, but confined to a tiny debug-only helper with limited reach.
"""


def _debug_dump(data: dict) -> None:
    """Debug-only helper, never called from a production code path."""
    if data:
        if "meta" in data:
            if data["meta"].get("verbose"):
                print(data)
