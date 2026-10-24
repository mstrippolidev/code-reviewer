from app.billing import charge_invoice
from app.invoices import load_invoice


def pay_invoice(invoice_id: int) -> dict:
    amount = load_invoice(invoice_id)
    receipt_id = charge_invoice(invoice_id, amount)
    return {"invoice_id": invoice_id, "receipt_id": receipt_id}
