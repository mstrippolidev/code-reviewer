"""
    COH gray-area fixture: a small module of text helpers with one function
    about parsing booleans. They are all string helpers, but they do not share a
    concept.
"""


def slugify(title: str) -> str:
    return "-".join(title.lower().split())


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
