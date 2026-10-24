_INVOICES = {1: 120.0, 2: 75.5}


def load_invoice(invoice_id: int) -> float:
    if invoice_id not in _INVOICES:
        raise KeyError(f"Invoice {invoice_id} does not exist")
    return _INVOICES[invoice_id]
