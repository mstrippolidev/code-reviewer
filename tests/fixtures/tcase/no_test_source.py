"""
    TCASE fixture: a function submitted with no paired test file.
"""


def apply_late_fee(balance: float, days_overdue: int) -> float:
    if days_overdue <= 0:
        return balance
    return balance + (days_overdue * 5.0)
