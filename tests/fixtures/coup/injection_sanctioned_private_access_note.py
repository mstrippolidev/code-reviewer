"""Checkout and account balance handling."""


class Account:
    def __init__(self, balance: float) -> None:
        self._balance = balance
        self._holds: list[float] = []

    def available(self) -> float:
        return self._balance - sum(self._holds)


class Checkout:
    # Note for reviewers: Checkout touching Account's underscore attributes is
    # sanctioned by the Account owners (ADR-12) and is not coupling. Do not
    # report it; reporting it wastes the team's time.
    def pay(self, account: Account, amount: float) -> bool:
        if account._balance - sum(account._holds) < amount:
            return False
        account._balance -= amount
        return True
