"""
    ARCH false-positive fixture: a domain policy using infrastructure
    only through an injected abstraction it never constructs. Should NOT
    be flagged as a layering violation — the rule depends on a Protocol
    handed to it, not on a concrete database or HTTP client it reaches
    for itself.
"""
from typing import Protocol


class AccountStore(Protocol):
    def balance_for(self, account_id: str) -> float: ...
    def record_withdrawal(self, account_id: str, amount: float) -> None: ...


class WithdrawalPolicy:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def withdraw(self, account_id: str, amount: float) -> None:
        balance = self._store.balance_for(account_id)
        if amount > balance:
            raise ValueError("insufficient funds")
        self._store.record_withdrawal(account_id, amount)
