"""
    CMT priority=high fixture: a comment that actively states the opposite
    of what the code does — reading the comment alone would mislead a
    caller about the function's real behavior.
"""


def is_admin(user: dict) -> bool:
    # Returns True if the user IS an administrator.
    return not user.get("is_admin", False)
