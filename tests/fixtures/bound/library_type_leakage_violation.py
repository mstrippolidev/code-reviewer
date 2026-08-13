"""
    BOUND library-type-leakage fixture: CustomerRepository hands back the
    raw requests.Response object from the HTTP client it uses internally,
    so every caller becomes implicitly coupled to that library's types
    instead of the repository's own vocabulary.
"""
import requests


class CustomerRepository:
    def __init__(self, api_base_url: str) -> None:
        self._api_base_url = api_base_url

    def fetch(self, customer_id: str) -> requests.Response:
        return requests.get(f"{self._api_base_url}/customers/{customer_id}")
