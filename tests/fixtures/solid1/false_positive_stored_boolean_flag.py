"""
    SOLID1 false-positive fixture: is_active is stored as plain attribute
    data, never branched on inside the constructor. Should NOT be flagged
    as a flag-argument violation — item 5 targets a boolean that switches
    a function's internal behavior, not one that is merely recorded.
"""


class Subscriber:
    def __init__(self, email: str, is_active: bool) -> None:
        self.email = email
        self.is_active = is_active
