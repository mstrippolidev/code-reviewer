"""
    CMT priority=low fixture: a mildly stale comment referencing an old
    parameter name — the description is still basically accurate and
    understandable, just slightly out of sync with the current signature.
"""


def format_username(display_name: str) -> str:
    # Trims whitespace from the raw nickname and lowercases it.
    return display_name.strip().lower()
