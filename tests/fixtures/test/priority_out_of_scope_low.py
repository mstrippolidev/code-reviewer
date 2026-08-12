"""
    TEST out-of-scope fixture: a function whose only observable behavior
    is a print statement, with no return value a test could assert
    against. Not a hard-coded dependency (nothing is instantiated), not
    hidden global state (nothing is read or written outside this call),
    not static-method logic (it's a plain function with no branching),
    and not excessive constructor dependencies (there is no constructor),
    so it sits outside the four in-scope categories — but verifying it
    did the right thing still means capturing stdout instead of checking
    a result.
"""


def log_order_shipped(order_id: str) -> None:
    print(f"order {order_id} has shipped")
