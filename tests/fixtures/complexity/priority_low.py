DEFAULT_EMAIL = "support@example.com"


def primary_email(contacts: list[dict]) -> str:
    for contact in contacts:
        if contact["is_primary"]:
            email = contact["email"]
            break
    else:
        email = DEFAULT_EMAIL
    return email
