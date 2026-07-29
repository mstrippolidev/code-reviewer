"""
    Error handling fixture: raises a generic built-in exception as a
    catch-all, where a custom exception would name the actual failure.
"""


def withdraw(balance: float, amount: float) -> float:
    if amount > balance:
        raise Exception("Not enough funds")
    return balance - amount
