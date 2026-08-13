"""
    CONC priority=medium fixture: a coroutine created but never awaited.
    notify_admins calls send_alert without awaiting or scheduling it, so
    the alert coroutine is created and silently discarded — it never
    actually runs.
"""


async def send_alert(message: str) -> None:
    print(f"ALERT: {message}")


async def notify_admins(incident: str) -> None:
    send_alert(f"incident reported: {incident}")
