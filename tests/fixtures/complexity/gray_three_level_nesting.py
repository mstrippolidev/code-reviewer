"""
    CMPLX gray-area fixture: nesting that goes three levels deep, one past the
    limit, where every level is a short, obvious check and the function is
    seven lines long.
"""


def first_active_email(users: list[dict]) -> str | None:
    for user in users:
        if user.get("active"):
            if user.get("email"):
                return user["email"]
    return None
