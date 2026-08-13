"""
    BOUND leaked-representation fixture: BankAccount hands out its own
    mutable transaction list directly, so external code can append,
    remove, or reorder transactions without ever going through a method
    that would keep the recorded balance consistent with the ledger.
"""


class BankAccount:
    def __init__(self, opening_balance: float) -> None:
        self.balance = opening_balance
        self.transactions: list[float] = []

    def deposit(self, amount: float) -> None:
        self.balance += amount
        self.transactions.append(amount)

    def get_transactions(self) -> list[float]:
        return self.transactions
