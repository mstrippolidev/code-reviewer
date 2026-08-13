"""
    ARCH priority=high fixture: a domain object issuing HTTP calls
    directly inside its own business logic. RefundPolicy is a business
    rule, but it reaches for a live payment gateway to decide whether a
    refund is allowed, so the rule cannot run or be tested without that
    gateway present.
"""
import requests


class RefundPolicy:
    def __init__(self, gateway_base_url: str) -> None:
        self._gateway_base_url = gateway_base_url

    def is_refundable(self, payment_id: str) -> bool:
        response = requests.get(f"{self._gateway_base_url}/payments/{payment_id}")
        payment = response.json()
        return payment["status"] == "captured" and not payment["disputed"]
