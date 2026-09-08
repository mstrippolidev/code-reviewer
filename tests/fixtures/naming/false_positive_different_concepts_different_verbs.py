"""
    VAR false-positive fixture: fetch_user and get_cached_region name two
    genuinely different operations — one is a remote lookup, the other a
    local in-memory read. Should NOT be flagged by item 3 — inconsistent
    vocabulary is for the SAME concept named two ways, not two different
    concepts that happen to both retrieve something.
"""


def fetch_user(user_id: str) -> dict[str, str]:
    return {"id": user_id}


def get_cached_region(region_code: str) -> str:
    return region_code.upper()
