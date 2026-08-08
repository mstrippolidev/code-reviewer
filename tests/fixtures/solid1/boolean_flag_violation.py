"""
    Boolean flag argument violation fixture: send_notification branches
    its entire behavior on the urgent flag, meaning it's really two
    responsibilities sharing one signature instead of a single function.
"""


def send_notification(message: str, urgent: bool) -> None:
    if urgent:
        print(f"SMS ALERT: {message}")
        print(f"Paging on-call: {message}")
    else:
        print(f"Email digest queued: {message}")
