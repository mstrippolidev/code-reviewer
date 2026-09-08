"""
    TEST false-positive fixture: reading a module-level constant that is
    never written to. Should NOT be flagged as hidden global state — item
    2 targets shared mutable state that makes one test's outcome depend
    on what ran before it; an immutable constant gives every test the
    same value every time, with nothing to isolate.
"""

MAX_RETRIES = 3


def should_retry(attempt_number: int) -> bool:
    return attempt_number < MAX_RETRIES
