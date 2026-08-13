"""
    CONC violation fixture: a non-atomic multi-step operation on a shared
    resource. transfer withdraws from one account and deposits into
    another as two separate, unguarded mutations, so a concurrent
    transfer interleaved between the two steps can corrupt both balances.
"""


class Account:
    def __init__(self, balance: float) -> None:
        self.balance = balance


def transfer(source: Account, destination: Account, amount: float) -> None:
    source.balance -= amount
    destination.balance += amount
