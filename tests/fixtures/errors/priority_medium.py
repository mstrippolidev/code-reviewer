"""
    ERR priority=medium fixture: a generic built-in exception used as a
    catch-all for a known business-rule violation, where a custom
    exception would let callers handle it specifically.
"""


class Account:
    def __init__(self, balance: float) -> None:
        self._balance = balance

    def withdraw(self, amount: float) -> None:
        if amount > self._balance:
            raise Exception("insufficient funds")
        self._balance -= amount
