"""
    TCASE out-of-scope fixture: both the normal path and the error path
    are exercised by the paired tests, so no path or edge case is
    literally uncovered — but the assertions are vacuous and verify
    nothing about the actual behavior, which is a real but different
    problem from the three in-scope considerations.
"""


def parse_config_value(raw: str) -> int:
    if not raw.strip():
        raise ValueError("empty config value")
    return int(raw.strip())
