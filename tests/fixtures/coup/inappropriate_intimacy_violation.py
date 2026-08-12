"""
    COUP violation fixture: inappropriate intimacy. ReportBuilder reads and
    assigns BankAccount's underscore-private attributes and depends on the
    internal shape of its ledger entries, so any change inside BankAccount
    silently breaks the builder.
"""


class BankAccount:
    def __init__(self, owner: str) -> None:
        self._owner = owner
        self._balance = 0.0
        self._ledger: list[dict] = []

    def deposit(self, amount: float) -> None:
        self._balance += amount
        self._ledger.append({"kind": "deposit", "amount": amount})

    def balance(self) -> float:
        return self._balance


class ReportBuilder:
    def build(self, account: BankAccount) -> str:
        deposits = [entry["amount"] for entry in account._ledger if entry["kind"] == "deposit"]
        account._balance = round(account._balance, 2)
        return f"{account._owner} deposited {sum(deposits)}"
