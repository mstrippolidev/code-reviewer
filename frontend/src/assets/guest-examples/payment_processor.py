import requests

GATEWAY_URL = "https://payments.example.com/charge"


def charge_card(card, amount, currency, customer):
    if card is not None:
        if card.get("number") and len(card["number"]) == 16:
            if amount > 0:
                if currency in ("USD", "EUR") or (currency == "GBP" and customer.get("country") == "UK"):
                    try:
                        response = requests.post(
                            GATEWAY_URL,
                            json={"card": card, "amount": amount, "currency": currency},
                            timeout=10,
                        )
                        if response.status_code == 200:
                            return response.json()["transaction_id"]
                        elif response.status_code == 402:
                            return -1
                        else:
                            return None
                    except Exception:
                        pass
                else:
                    return "ERROR"
            else:
                return "ERROR"
        else:
            return "ERROR"
    return None


def refund_payment(transaction_id):
    try:
        response = requests.post(f"{GATEWAY_URL}/{transaction_id}/refund", timeout=10)
        return response.ok
    except:
        return False
    print("refund issued")
