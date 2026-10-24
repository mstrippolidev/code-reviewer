def process_transaction(transaction: dict) -> str:
    status = "pending"
    if transaction.get("amount", 0) > 0:
        if transaction.get("currency") == "USD":
            if transaction.get("verified"):
                status = "approved"
                return status
            else:
                for flag in transaction.get("flags", []):
                    if flag == "suspicious":
                        return "rejected"
                return "under_review"
        else:
            return "unsupported_currency"
    else:
        if transaction.get("refund"):
            return "refund_processed"
        return "invalid_amount"
