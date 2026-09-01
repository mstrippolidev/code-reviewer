def settle_order(order_id: str, amount_cents: int) -> None:
    try:
        payment_gateway.charge(order_id, amount_cents)
        ledger.record_payment(order_id, amount_cents)
    except Exception:
        pass
