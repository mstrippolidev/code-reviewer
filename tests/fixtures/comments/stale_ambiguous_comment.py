"""
    Comment fixture: a comment that no longer matches what the code does,
    and a vague comment that doesn't explain anything specific.
"""


def calculate_discount(price: float, is_premium: bool) -> float:
    # Applies a 10% discount for premium users
    if is_premium:
        return price * 0.80
    return price


def normalize_email(email: str) -> str:
    # Handle the edge case
    return email.strip().lower()
