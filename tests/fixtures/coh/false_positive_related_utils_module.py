"""
    COH false-positive fixture: three functions, all about the same
    concept (a date range). Should NOT be flagged as a grab-bag module —
    the prompt's own carve-out is a module with two or three closely
    related functions, and every function here shares both purpose and
    the same (start, end) shape.
"""
from datetime import date


def format_date_range(start: date, end: date) -> str:
    return f"{start.isoformat()} - {end.isoformat()}"


def parse_date_range(text: str) -> tuple[date, date]:
    start_text, end_text = text.split(" - ")
    return date.fromisoformat(start_text), date.fromisoformat(end_text)


def is_within_range(day: date, start: date, end: date) -> bool:
    return start <= day <= end
