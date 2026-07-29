"""
    Error handling fixture: a custom exception and an explicit raise on the
    failure path, with no dead code. None of this should be flagged.
"""


class InsufficientFundsError(Exception):
    """Raised when an account does not have enough balance to cover a withdrawal."""


def withdraw(balance: float, amount: float) -> float:
    if amount > balance:
        raise InsufficientFundsError(f"Cannot withdraw {amount}, balance is {balance}")
    return balance - amount
