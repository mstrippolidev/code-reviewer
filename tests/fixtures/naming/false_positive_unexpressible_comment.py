"""
    VAR false-positive fixture: the comment states a business rule no
    name could carry, not a unit/qualifier the identifier omitted.
    Should NOT be flagged by item 4 — the prompt's own distinction is a
    comment compensating for something a name COULD have said; this one
    describes something a name genuinely couldn't express at all.
"""


def refund_amount(order_total: float) -> float:
    # Refunds are capped at 90% of the order total per the 2024 chargeback policy.
    return min(order_total, order_total * 0.9)
