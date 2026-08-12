"""
    TEST violation fixture: a hard-coded dependency. PaymentProcessor
    builds its own StripeClient inside __init__, so a test cannot
    substitute a fake without patching internals.
"""


class StripeClient:
    def charge(self, amount: float, token: str) -> str:
        return f"charged {amount} via stripe token {token}"


class PaymentProcessor:
    def __init__(self) -> None:
        self._client = StripeClient()

    def process(self, amount: float, token: str) -> str:
        return self._client.charge(amount, token)
