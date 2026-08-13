"""
    BOUND false-positive fixture: ProductRepository uses requests
    internally but never returns the raw response — it converts the
    payload into its own Product objects before handing anything back.
    Should NOT be flagged as library-type leakage — nothing about
    requests crosses the public boundary.
"""
from dataclasses import dataclass

import requests


@dataclass
class Product:
    product_id: str
    name: str


class ProductRepository:
    def __init__(self, api_base_url: str) -> None:
        self._api_base_url = api_base_url

    def fetch(self, product_id: str) -> Product:
        response = requests.get(f"{self._api_base_url}/products/{product_id}")
        payload = response.json()
        return Product(payload["id"], payload["name"])
