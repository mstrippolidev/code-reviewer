"""
    COH violation fixture: a module-level grab bag of top-level functions
    grouped only by convenience — string formatting, date math, and email
    delivery share a file but no purpose.
"""
from datetime import date, timedelta


def slugify(title: str) -> str:
    return title.strip().lower().replace(" ", "-")


def truncate(text: str, max_length: int) -> str:
    return text if len(text) <= max_length else text[:max_length] + "..."


def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def send_email(to_address: str, subject: str, body: str) -> None:
    print(f"sending '{subject}' to {to_address}: {body}")
