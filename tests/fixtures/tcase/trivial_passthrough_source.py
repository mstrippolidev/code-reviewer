"""
    TCASE false-positive fixture, no test file paired: a bare constant
    with no branches. Should NOT be flagged even with no test file
    submitted — the prompt's own carve-out is code with no testable
    behavior at all, e.g. a bare constant or trivial passthrough.
"""

DEFAULT_PAGE_SIZE = 25
