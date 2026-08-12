"""
    SOLID1 priority=medium fixture: a function doing more than one
    conceptual thing — validating input, persisting it, and logging the
    result, all in one body.
"""


def register_user(email: str, password: str) -> None:
    if "@" not in email:
        raise ValueError("invalid email")
    user_id = _save_user_to_db(email, password)
    print(f"User {user_id} registered")


def _save_user_to_db(email: str, password: str) -> int:
    return hash((email, password)) % 100000
