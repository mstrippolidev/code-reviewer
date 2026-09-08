"""
    CMPLX false-positive fixture: a boolean condition with exactly three
    parts. Should NOT be flagged by item 2 — the rule targets MORE than
    3 parts joined by and/or; three is the boundary, not a violation of
    it.
"""


def is_eligible(age: int, has_license: bool, passed_exam: bool) -> bool:
    return age >= 18 and has_license and passed_exam
