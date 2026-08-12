"""
    CMPLX priority=medium fixture: a flat, un-nested boolean condition with
    four parts. It hides which part actually decides the outcome, but is
    still followable top to bottom.
"""


def is_eligible_for_discount(user: dict) -> bool:
    return (
        user.get("is_member")
        and user.get("account_age_days", 0) > 30
        and user.get("purchase_count", 0) > 5
        and not user.get("has_pending_refund")
    )
