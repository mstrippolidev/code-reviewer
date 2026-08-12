"""
    COUP priority=low fixture: a single one-step-too-far navigation.
    ReceiptPrinter reaches through Purchase into its one Item rather than
    being handed the item directly, but the chain is only one hop and the
    impact is minor.
"""


class Item:
    def __init__(self, name: str) -> None:
        self.name = name


class Purchase:
    def __init__(self, item: Item) -> None:
        self.item = item


class ReceiptPrinter:
    def print_receipt(self, purchase: Purchase) -> str:
        return f"Receipt for {purchase.item.name}"
