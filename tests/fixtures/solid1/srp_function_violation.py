"""
    Function-level SRP violation fixture: register_user validates input,
    persists the record, and sends a notification all in one body — three
    conceptually separate responsibilities living in one function,
    regardless of its short length.
"""


def register_user(name: str, email: str) -> dict:
    if not name or "@" not in email:
        raise ValueError("Invalid name or email")

    user = {"name": name, "email": email}
    print(f"INSERT INTO users VALUES ({name}, {email})")

    print(f"Sending welcome email to {email}")

    return user
