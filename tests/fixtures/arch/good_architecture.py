"""
    ARCH fixture demonstrating healthy layering: the domain rule works on
    values it is given, persistence is reached only through a collaborator
    handed in from outside, and nothing here builds its own object graph.
    None of this should be flagged.
"""
from decimal import Decimal
from typing import Protocol


class InvoiceStore(Protocol):
    def save_total(self, invoice_id: str, total: Decimal) -> None: ...


class InvoiceTotal:
    """Pure business rule: knows how a total is calculated, nothing else."""

    def __init__(self, tax_rate: Decimal) -> None:
        self._tax_rate = tax_rate

    def for_lines(self, line_amounts: list[Decimal]) -> Decimal:
        subtotal = sum(line_amounts, Decimal("0"))
        return subtotal + (subtotal * self._tax_rate)


class InvoiceService:
    """Application layer: sequences the rule and the store, owning neither."""

    def __init__(self, total_rule: InvoiceTotal, store: InvoiceStore) -> None:
        self._total_rule = total_rule
        self._store = store

    def finalize(self, invoice_id: str, line_amounts: list[Decimal]) -> Decimal:
        total = self._total_rule.for_lines(line_amounts)
        self._store.save_total(invoice_id, total)
        return total
