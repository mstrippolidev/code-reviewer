"""
    COH false-positive fixture: from_row is an alternate-constructor
    classmethod that only touches its arguments, never self. Should NOT
    be flagged as a method ignoring self — it takes cls, not self, and
    building the instance it returns is exactly this class's purpose.
"""


class Invoice:
    def __init__(self, invoice_id: str, total_cents: int) -> None:
        self.invoice_id = invoice_id
        self.total_cents = total_cents

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "Invoice":
        return cls(invoice_id=str(row["id"]), total_cents=int(row["total_cents"]))

    def total_dollars(self) -> float:
        return self.total_cents / 100
