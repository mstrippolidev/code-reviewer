"""
    Naming fixture: three different verbs used for the same kind of
    operation (fetching user-related data by id), which VAR should flag as
    inconsistent vocabulary.
"""


def get_user(user_id: int) -> dict:
    return {"id": user_id}


def fetch_user_profile(user_id: int) -> dict:
    return {"id": user_id, "profile": {}}


def retrieve_user_settings(user_id: int) -> dict:
    return {"id": user_id, "settings": {}}
