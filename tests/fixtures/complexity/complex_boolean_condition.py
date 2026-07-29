"""
    Complexity fixture: a single condition joining five clauses, hiding
    which parts actually decide the outcome.
"""


def is_eligible_for_loan(applicant: dict) -> bool:
    if (
        applicant["age"] >= 18
        and applicant["credit_score"] > 650
        and applicant["income"] > 30000
        and not applicant["has_defaulted"]
        and applicant["employment_years"] >= 2
    ):
        return True
    return False
