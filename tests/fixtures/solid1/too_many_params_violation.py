"""
    Too-many-parameters violation fixture: create_invoice takes 6
    parameters, a sign it's coordinating too much and that several of them
    belong together in their own type.
"""


def create_invoice(
    customer_name: str,
    customer_email: str,
    line_items: list[dict],
    tax_rate: float,
    discount_percent: float,
    due_date: str,
) -> dict:
    subtotal = sum(item["price"] * item["quantity"] for item in line_items)
    discounted = subtotal * (1 - discount_percent / 100)
    total = discounted * (1 + tax_rate / 100)
    return {
        "customer_name": customer_name,
        "customer_email": customer_email,
        "total": total,
        "due_date": due_date,
    }
